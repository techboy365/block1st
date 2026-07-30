import smtplib
import re
import uuid
import socks  # PySocks
import socket
import json
import random
import string
from datetime import datetime
import logging
import colorama
from colorama import Fore, Style
import os
import time
from email.utils import formatdate
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from datetime import datetime, timedelta
from email import encoders
from faker import Faker
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError
import concurrent.futures
import threading
import pdfkit  # For HTML-to-PDF conversion
import itertools
from colorama import Fore, Style, init
from exchangelib import Credentials, Configuration, Account, DELEGATE, HTMLBody, Message, Mailbox, FileAttachment
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter

# -------------------------
# INITIALIZATION
# -------------------------
init(autoreset=True)
logger = logging.getLogger(__name__)
fake = Faker()

# -------------------------
# Disable InsecureRequestWarnings from urllib3
# -------------------------
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Initialize Faker for generating random names
fake = Faker()

# Global lock to protect sent_count updates in multi-threaded mode.
sent_count_lock = threading.Lock()


# -------------------------
# CONSTANTS
# -------------------------
SMTP_SUCCESS_CODES = {250, 251, 354}
TEMPORARY_ERROR_CODES = {421, 450, 451, 452}
PERMANENT_ERROR_CODES = {500, 501, 502, 503, 504, 550, 551, 552, 553, 554}

# ===========================================================
# HEADER RANDOMIZATION UTILITIES
# ===========================================================

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Microsoft Outlook/16.0.14326.20404',
    'Thunderbird/91.4.1',
    'Apple Mail/14.0',
    'Opera Mail/3.0',
    'The Bat! (v10.0.0.1)',
]

X_MAILERS = [
    'Microsoft Outlook 16.0',
    'Thunderbird 91.4',
    'Apple Mail (2.3845)',  # Fixed quote here
    'Windows Live Mail 2019',
    'Postbox 7.0',
]

def generate_message_id(domain):
    """Create RFC-compliant Message-ID with random components"""
    rand_uuid = uuid.uuid4().hex
    timestamp = hex(int(time.time()))[2:]
    return f'<{timestamp}.{rand_uuid}@{domain}>'

def random_date():
    """Generate date with random offset (-2h to +2h)"""
    offset = random.randint(-7200, 7200)
    return (datetime.now() + timedelta(seconds=offset)).strftime('%a, %d %b %Y %H:%M:%S %z')

# -------------------------
# COLORED LOGGING SETUP (PUT THIS FIRST)
# -------------------------
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'WARNING': Fore.YELLOW,
        'INFO': Fore.CYAN,
        'DEBUG': Fore.BLUE,
        'CRITICAL': Fore.RED,
        'ERROR': Fore.RED,
        'SUCCESS': Fore.GREEN
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, Fore.WHITE)
        return f"{color}{super().format(record)}{Style.RESET_ALL}"

# -------------------------
# INITIALIZATION (PUT THIS AFTER FORMULER DEFINITION)
# -------------------------
init(autoreset=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter(
    '%(asctime)s - %(message)s', 
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(handler)

class AtomicCounter:
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._value += 1
            return self._value

    @property
    def value(self):
        return self._value

# -------------------------
# EMAIL COMPONENTS
# -------------------------
def load_links_file(links_file):
    """Load links from file for %LINK% replacement"""
    if not os.path.isfile(links_file):
        return []
    with open(links_file, 'r', encoding='utf-8') as f:
        return [ln.strip() for ln in f if ln.strip()]

def replace_tags(text, recipient_email, links_list=None):
    """Replace placeholder tags in text"""
    first_name, last_name = fake.first_name(), fake.last_name()
    domain_part = recipient_email.split('@')[1].split('.')[0].capitalize()
    
    replacements = {
        "%DOMAIN%": domain_part,
        "%EMAIL%": recipient_email,
        "%DATE%": datetime.now().strftime("%Y-%m-%d"),
        "%TIME%": datetime.now().strftime("%H:%M:%S"),
        "%RANDOMENUM%": ''.join(random.choices(string.digits, k=8)),
        "%FIRSTNAME%": first_name,
        "%LAST%": last_name,
        "%FULLNAME%": f"{first_name} {last_name}",
        "%DOMAIN_FIRSTNAME%": f"{domain_part}_{first_name}",
        "%LINK%": random.choice(links_list) if links_list else ""
    }
    
    for tag, val in replacements.items():
        text = text.replace(tag, val)
    return text

def read_recipients(recipient_file):
    """Read recipient list from file"""
    with open(recipient_file, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]
		
		
def load_message_body(body_file, recipient_email, body_type='plain', links_list=None):
    """Load the email body from a file and perform placeholder replacements."""
    if body_file and os.path.exists(body_file):
        with open(body_file, 'r', encoding='utf-8') as f:
            body = f.read()
            return replace_tags(body, recipient_email, links_list)
    return ""  # <-- MISSING CLOSING QUOTE ADDED HERE

# -----------------------------------------------------------
# B. PROXY CONFIG & CHECKING
# -----------------------------------------------------------
def setup_socks_proxy(current_proxy):
    """Set up S5 proxy and return original socket for restoration"""
    original_socket = socket.socket
    if current_proxy:
        auth = current_proxy.get('auth', {})
        socks.set_default_proxy(
            socks.SOCKS5,
            current_proxy['host'],
            current_proxy['port'],
            username=auth.get('user'),
            password=auth.get('pass')
        )
        socket.socket = socks.socksocket
    return original_socket  # Return original to reset later
        
# Corrected code structure
def check_network_access(host, port=25, timeout=5, proxy=None):
    """Check connectivity through proxy if provided"""
    original_socket = socket.socket  # Save original socket class
    try:
        if proxy:
            # Set up proxy and get replacement socket class
            setup_socks_proxy(proxy)
            sock = socks.socksocket()
        else:
            # Use regular socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception as e:
        logger.error(f"{Fore.RED}Network error {host}:{port} - {e}{Style.RESET_ALL}")
        return False
    finally:
        if proxy:
            # Restore original socket implementation
            socket.socket = original_socket
            logger.debug(f"{Fore.CYAN}Reset socket to default implementation{Style.RESET_ALL}")
            
def validate_proxy(proxy, test_host="8.8.8.8", test_port=53, timeout=10):
    """Validate proxy connectivity"""
    try:
        socks.set_default_proxy(socks.SOCKS5, proxy['host'], proxy['port'],
                               proxy.get('auth', {}).get('user'),
                               proxy.get('auth', {}).get('pass'))
        with socks.socksocket() as s:
            s.settimeout(timeout)
            s.connect((test_host, test_port))
        return True
    except Exception as e:
        logger.error(f"{Fore.RED}Proxy failed: {proxy['host']}:{proxy['port']} - {e}{Style.RESET_ALL}")
        return False

def get_socks5_proxies(config):
    """Return the list of S5 from config if use_sock is true."""
    if config.get('use_sock', False):
        proxies = config.get('sock5_proxies', [])
        if not proxies:
            logger.error(f"{Fore.RED}No S5 Resources found in configuration.{Style.RESET_ALL}")
        return proxies
    return []
		
# -----------------------------------------------------------
# NEW: HTML TO PDF GENERATION IN MEMORY (WITH UNIQUE METADATA)
# -----------------------------------------------------------
def generate_pdf_bytes_from_html(html_file, recipient_email, links_list):
    """
    Read the HTML file, replace tags within its content, then generate PDF bytes.
    The PDF is generated in memory (not saved to disk). After generation, unique
    metadata is injected into the PDF using PyPDF2.
    """
    options = {
       'page-size': 'A4',
       'margin-top': '0.75in',
       'margin-right': '0.75in',
       'margin-bottom': '0.75in',
       'margin-left': '0.75in',
       'encoding': "UTF-8",
       'no-outline': None,
    }
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        html_content = replace_tags(html_content, recipient_email, links_list)
        path_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
        config_pdfkit = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
        pdf_bytes = pdfkit.from_string(html_content, False, options=options, configuration=config_pdfkit)
        logger.info(f"{Fore.GREEN}PDF generated for {recipient_email} from {html_file}{Style.RESET_ALL}")
        
        # Add unique metadata using PyPDF2
        try:
            import io
            from PyPDF2 import PdfReader, PdfWriter
            pdf_in_memory = io.BytesIO(pdf_bytes)
            pdf_reader = PdfReader(pdf_in_memory)
            pdf_writer = PdfWriter()
            for page in pdf_reader.pages:
                pdf_writer.add_page(page)
            unique_metadata = {
                '/Title': replace_tags("PDF for %EMAIL% on %DATE% %TIME% - %RANDOMENUM%", recipient_email, links_list),
                '/Author': replace_tags("%FULLNAME%", recipient_email, links_list),
                '/Subject': replace_tags("Unique PDF - %DOMAIN_FIRSTNAME%", recipient_email, links_list),
                '/Keywords': replace_tags("%DOMAIN% %FIRSTNAME% %LAST%", recipient_email, links_list)
            }
            pdf_writer.add_metadata(unique_metadata)
            output = io.BytesIO()
            pdf_writer.write(output)
            pdf_bytes = output.getvalue()
            output.close()
            logger.info(f"{Fore.GREEN}Unique metadata added for {recipient_email}'s PDF{Style.RESET_ALL}")
        except Exception as meta_e:
            logger.error(f"{Fore.RED}Error adding metadata to PDF: {meta_e}{Style.RESET_ALL}")
        return pdf_bytes
    except Exception as e:
        logger.error(f"{Fore.RED}Error generating PDF from HTML: {e}{Style.RESET_ALL}")
        return None
		
# ===========================================================
# FIXED & ENHANCED CORE COMPONENTS
# ===========================================================

def get_random_from_email(from_field):
    """Improved email selection with validation."""
    if not from_field:
        raise ValueError("Empty from_field provided")
    emails = [email.strip() for email in re.split(r'[;,]\s*', from_field)]
    return random.choice(emails) if emails else ''

def verify_email_delivery(test_email, config, current_proxy=None):
    """Send verification email using actual campaign configuration"""
    try:
        logger.info(f"{Fore.CYAN}Starting verification email to {test_email}{Style.RESET_ALL}")
        
        # Use first SMTP server from config
        smtp_config = config['smtp_servers'][0]
        
        # Get actual campaign components
        from_email = get_random_from_email(smtp_config.get('from_email', ''))
        sender_name = config.get('sender_name', '')
        subject = replace_tags(config.get('subject', 'Test Email'), test_email, config.get('links_list', []))
        body = load_message_body(config.get('message_body', ''), test_email, 'plain', config.get('links_list', []))
        
        # Generate attachments if needed
        attachment_data = None
        attach_name = None
        if config.get("html2pdf", False):
            html_file = replace_tags(config.get('html2pdf_file', ''), test_email, config.get('links_list', []))
            pdf_bytes = generate_pdf_bytes_from_html(html_file, test_email, config.get('links_list', []))
            if pdf_bytes:
                attachment_data = pdf_bytes
                attach_name = replace_tags(config.get('html2pdf_attachment_name', 'document.pdf'), test_email, config.get('links_list', []))
        
        # Create connection
        server = create_smtp_connection(
            smtp_config,
            use_sock=bool(current_proxy),
            current_proxy=current_proxy,
            timeout=15
        )
        
        if not server:
            raise Exception("Failed to create verification connection")

        # Build actual campaign email
        msg = prepare_email_message(
            sender_name=sender_name,
            from_email=from_email,
            recipient_email=test_email,
            subject=subject,
            body=body,
            attachment_path=None,
            attachment_name=attach_name,
            body_type=config.get('message_body_type', 'plain'),
            attachment_data=attachment_data
        )

        # Send using actual configuration
        server.sendmail(from_email, [test_email], msg)
        server.quit()
        
        logger.info(f"{Fore.GREEN}Verification email sent successfully using campaign config{Style.RESET_ALL}")
        return True
        
    except Exception as e:
        logger.error(f"{Fore.RED}Verification failed: {str(e)}{Style.RESET_ALL}")
        return False
		
# ===========================================================
# COLORED LOGGING SETUP
# ===========================================================

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'WARNING': Fore.YELLOW,
        'INFO': Fore.CYAN,
        'DEBUG': Fore.BLUE,
        'CRITICAL': Fore.RED,
        'ERROR': Fore.RED,
        'SUCCESS': Fore.GREEN
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, Fore.WHITE)
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter(
    '%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(handler)


# ===========================================================
# OPTIMIZED CONNECTION CORE
# ===========================================================

class TurboSMTPConnection:
    __slots__ = ['conn', 'last_used', 'use_count']
    
    def __init__(self, smtp_connection):
        self.conn = smtp_connection
        self.last_used = time.monotonic()
        self.use_count = 0

    def send(self, from_addr, to_addr, msg):
        try:
            self.conn.sendmail(from_addr, to_addr, msg)
            self.use_count += 1
            self.last_used = time.monotonic()
            return True
        except Exception as e:
            logger.error(f"Send failed: {str(e)}")
            return False

    def is_alive(self):
        try:
            return self.conn.noop()[0] == 250
        except:
            return False

class TurboConnectionPool:
    def __init__(self, smtp_configs, proxies=None, max_connections=200):  # Increased from 20
        self.smtp_configs = itertools.cycle(smtp_configs)
        self.proxies = itertools.cycle(proxies) if proxies else None
        self.pool = []
        self.lock = threading.RLock()  # Changed to reentrant lock
        self.max_connections = max_connections
        self._warm_pool(50)  # Start with 50 connections

    def _add_connection(self):
        """Aggressive connection creation"""
        try:
            for _ in range(5):  # Try 5 times to create connection
                config = next(self.smtp_configs)
                proxy = next(self.proxies) if self.proxies else None
                
                conn = create_smtp_connection(
                    config,
                    proxy=proxy,
                    timeout=5  # Reduced from 10
                )
                
                if conn:
                    self.pool.append(TurboSMTPConnection(conn))
                    return
        except Exception as e:
            logger.error(f"Connection failed: {str(e)}")

    def get_connection(self):
        with self.lock:
            # Clean dead connections
            self.pool = [c for c in self.pool if c.is_alive()]
            
            # Prioritize least used connection
            if self.pool:
                conn = min(self.pool, key=lambda x: x.use_count)
                return conn
            
            # Create new if under limit
            if len(self.pool) < self.max_connections:
                self._add_connection()
                return self.pool[-1] if self.pool else None
            
            return None
			
# ===========================================================
# HIGH-SPEED EMAIL SENDER
# ===========================================================

def turbo_send(
    config,
    recipients,
    template_data,
    proxies=None,
    workers=50,
    retries=2
):
    logger.info(f"{Fore.GREEN}Starting turbo send mode with {workers} workers{Style.RESET_ALL}")
    
    pool = TurboConnectionPool(
        config['smtp_servers'],
        proxies=proxies,
        max_connections=workers*2
    )

    # Thread-safe counters
    success_counter = AtomicCounter()
    failure_counter = AtomicCounter()
    total = len(recipients)
    start_time = time.monotonic()

    def _send_worker(recipient):
        """Worker function without nonlocal variables"""
        msg = build_message(recipient, template_data)
        
        # Immediate retry without delay
        for _ in range(retries + 1):
            conn = pool.get_connection()
            if not conn:
                continue
                
            try:
                if conn.send(config['from_email'], recipient, msg):
                    success_counter.increment()
                    logger.debug(f"Sent to {recipient}")
                    return True
                else:
                    failure_counter.increment()
                    logger.debug(f"Failed to send to {recipient}")
            except Exception as e:
                logger.error(f"Error sending to {recipient}: {str(e)}")
                failure_counter.increment()
                
        return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_send_worker, r): r for r in recipients}
        
        # Fast async processing
        for future in concurrent.futures.as_completed(futures):
            _ = future.result()  # Results already handled by counters

    duration = time.monotonic() - start_time
    logger.info(f"""
    {Fore.CYAN}Turbo Send Complete{Style.RESET_ALL}
    ==========================
    {Fore.GREEN}Success: {success_counter.value}{Style.RESET_ALL}
    {Fore.RED}Failures: {failure_counter.value}{Style.RESET_ALL}
    {Fore.YELLOW}Duration: {duration:.1f}s{Style.RESET_ALL}
    {Fore.BLUE}Rate: {success_counter.value/max(duration, 0.1):.1f} emails/s{Style.RESET_ALL}
    """)

def build_message(recipient, template_data):
    msg = MIMEMultipart()
    # Add your message building logic here
    msg.attach(MIMEText(template_data['body'], 'html'))  # Ensure body is attached
    return msg.as_string()
	
# ===========================================================
# CONNECTION CORE IMPLEMENTATION
# ===========================================================

class SMTPConnectionWrapper:
    __slots__ = ['conn', 'state', 'transaction_count', 'last_activity', 'created_at']
    
    def __init__(self, smtp_connection):
        self.conn = smtp_connection
        self.state = 'ready'
        self.transaction_count = 0
        self.last_activity = time.monotonic()
        self.created_at = time.monotonic()

    def begin_session(self):
        try:
            if self.conn.sock is None:
                self.state = 'dead'
                return
            self.conn.rset()
            self.state = 'ready'
            self.transaction_count = 0
            self.last_activity = time.monotonic()
        except (smtplib.SMTPServerDisconnected, ConnectionResetError):
            self.state = 'dead'
        except Exception as e:
            logger.error(f"Session reset failed: {str(e)}")
            self.state = 'dead'

    def send_email(self, from_addr, to_addr, msg_str):
        try:
            if self.state == 'dead':
                return False

            logger.info(f"Sending to {to_addr}")
            start_time = time.monotonic()
            
            self.conn.mail(from_addr)
            self.conn.rcpt(to_addr)
            self.conn.data(msg_str)
            
            self.transaction_count += 1
            self.last_activity = time.monotonic()
            duration = (time.monotonic() - start_time) * 1000
            logger.info(f"Successfully sent to {to_addr} ({duration:.1f}ms)")
            return True
        except smtplib.SMTPResponseException as e:
            logger.error(f"SMTP Error {e.smtp_code}: {str(e)}")
            self.state = 'dead'
        except (smtplib.SMTPServerDisconnected, ConnectionResetError):
            self.state = 'dead'
        except Exception as e:
            logger.error(f"Critical error: {str(e)}")
            self.state = 'dead'
        return False

    def close(self):
        try:
            if self.state != 'dead' and self.conn.sock:
                self.conn.quit()
                self.conn.sock.close()
        except Exception as e:
            logger.debug(f"Close error: {str(e)}")
        finally:
            self.state = 'dead'

    def is_healthy(self):
        try:
            if self.conn.sock is None:
                return False
            self.conn.noop()
            return True
        except Exception as e:
            self.state = 'dead'
            return False

class SMTPConnectionPool:
    def __init__(self, smtp_configs, proxy_list=None, max_reuse=500, max_age=600, min_connections=50):
        self.smtp_configs = itertools.cycle(smtp_configs)
        self.proxies = itertools.cycle(proxy_list) if proxy_list else None
        self.connections = []
        self.lock = threading.Lock()
        self.max_reuse = max_reuse  # Increased from 100
        self.max_age = max_age      # Increased from 300
        self.min_connections = min_connections  # Increased from 5

        self.keepalive_thread = threading.Thread(target=self._maintain_connections, daemon=True)
        self.keepalive_thread.start()
        self._warm_pool()

    def _warm_pool(self):
        """Initialize connection pool with more connections"""
        with self.lock:
            for _ in range(self.min_connections * 2):  # Create double the minimum
                conn = self._create_connection()
                if conn: 
                    self.connections.append(conn)

    def _create_connection(self):
        """Faster connection creation with retries"""
        try:
            for _ in range(3):  # Retry up to 3 times
                config = next(self.smtp_configs)
                proxy = next(self.proxies) if self.proxies else None
                
                server = create_smtp_connection(
                    config, 
                    use_sock=bool(proxy),
                    current_proxy=proxy,
                    timeout=10  # Reduced from 15
                )
                
                if server:
                    return SMTPConnectionWrapper(server)
            return None
        except Exception as e:
            logger.debug(f"Connection failed: {str(e)}")  # Changed to debug level
            return None

    def _maintain_connections(self):
        """More aggressive connection maintenance"""
        while True:
            with self.lock:
                now = time.monotonic()
                # Keep healthy connections only
                self.connections = [conn for conn in self.connections if conn.is_healthy()]
                
                # Remove expired connections
                self.connections = [
                    conn for conn in self.connections
                    if (now - conn.created_at) < self.max_age
                    and conn.transaction_count < self.max_reuse
                ]
                
                # Maintain pool size with burst creation
                while len(self.connections) < self.min_connections * 2:
                    new_conn = self._create_connection()
                    if new_conn: 
                        self.connections.append(new_conn)
                        if len(self.connections) >= self.min_connections * 2:
                            break
            time.sleep(2)  # More frequent maintenance (reduced from 5)

    def get_connection(self):
        """Optimized connection retrieval"""
        with self.lock:
            # Return first available ready connection
            for conn in self.connections:
                if conn.state == 'ready' and conn.is_healthy():
                    conn.begin_session()
                    return conn
            
            # Create new connection if under limit
            if len(self.connections) < self.min_connections * 3:
                new_conn = self._create_connection()
                if new_conn:
                    self.connections.append(new_conn)
                    return new_conn
            
            # Fallback to any healthy connection
            for conn in self.connections:
                if conn.is_healthy():
                    conn.begin_session()
                    return conn
            
            return None

    def retire_connection(self, connection):
        """Safer retirement with health check"""
        with self.lock:
            try:
                if connection in self.connections:
                    if not connection.is_healthy():
                        self.connections.remove(connection)
                        connection.close()
                    else:
                        connection.begin_session()  # Reset for reuse
            except Exception as e:
                logger.debug(f"Retirement error: {str(e)}")

    # NEW METHOD TO FIX ERROR
    def retire_all_connections(self):
        """Force close all connections in the pool"""
        with self.lock:
            logger.info(f"Closing {len(self.connections)} connections")
            for conn in self.connections:
                try:
                    conn.close()
                except Exception as e:
                    logger.debug(f"Error closing connection: {str(e)}")
            self.connections.clear()

# ===========================================================
# EMAIL CONSTRUCTION WITH RANDOMIZED HEADERS
# ===========================================================

def prepare_email_message(
    sender_name: str,
    from_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    attachment_path: str,
    attachment_name: str,
    body_type: str,
    attachment_data: bytes
) -> str:
    msg = MIMEMultipart()
    
    # Core headers
    msg['From'] = f"{sender_name} <{from_email}>"
    msg['To'] = recipient_email
    msg['Subject'] = subject
    
    # Randomized headers
    msg['Message-ID'] = generate_message_id(from_email.split('@')[-1])
    msg['Date'] = random_date()
    msg['User-Agent'] = random.choice(USER_AGENTS)
    msg['X-Mailer'] = random.choice(X_MAILERS)
    msg['X-Originating-IP'] = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    msg['X-Priority'] = str(random.randint(1,3))
    
    # Optional headers (50% chance)
    if random.random() > 0.5:
        msg['X-MSMail-Priority'] = random.choice(['High', 'Normal', 'Low'])
    if random.random() > 0.7:
        msg['Importance'] = random.choice(['high', 'normal', 'low'])

    # Message body
    msg.attach(MIMEText(body, body_type))

    # Attachments
    if attachment_path and not attachment_data:
        try:
            with open(attachment_path, "rb") as f:
                attachment_data = f.read()
        except Exception as e:
            logger.error(f"Attachment read failed: {str(e)}")

    if attachment_data:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(attachment_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 
                      f'attachment; filename="{attachment_name}"')
        msg.attach(part)

    return msg.as_string()

# ===========================================================
# BATCH SENDING IMPLEMENTATION
# ===========================================================

def send_batch_emails(
    config: dict,
    recipients_chunk: list,
    max_retries: int,
    max_errors_before_stop: int,
    sent_count: list,
    total_recipients: int,
    links_list: list,
    connection_pool: SMTPConnectionPool,
    threads: int = 15
) -> bool:
    sender_name_template = config.get('sender_name', 'Default Sender')
    subject_template = config.get('subject', 'Default Subject')
    body_template = config.get('message_body', '')
    from_email = get_random_from_email(config['smtp_servers'][0].get('from_email', ''))
    
    pdf_gen = None
    if config.get("html2pdf", False):
        pdf_gen = setup_pdf_generator(config)

    # Thread-safe counters
    error_counter = AtomicCounter()
    success_counter = AtomicCounter()
    start_time = time.monotonic()

    def _process_recipient(recipient: str) -> bool:
        """Process individual recipient without nonlocal variables"""
        try:
            msg = prepare_email_message(
                sender_name=replace_tags(sender_name_template, recipient, links_list),
                from_email=from_email,
                recipient_email=recipient,
                subject=replace_tags(subject_template, recipient, links_list),
                body=replace_tags(body_template, recipient, links_list),
                attachment_path=None,
                attachment_name="document.pdf" if pdf_gen else "",
                body_type=config.get('message_body_type', 'plain'),
                attachment_data=pdf_gen(recipient) if pdf_gen else None
            )
        except Exception as e:
            logger.error(f"Message prep failed for {recipient}: {str(e)}")
            error_counter.increment()
            return False

        # Fast retry loop without delays
        for attempt in range(max_retries + 1):
            conn = connection_pool.get_connection()
            if not conn:
                continue

            try:
                if conn.send_email(from_email, recipient, msg):
                    success_counter.increment()
                    sent_count[0] = success_counter.value  # Atomic update
                    logger.debug(f"Progress: {success_counter.value}/{total_recipients}")
                    return True
                
                # Only retire if connection is bad
                if not conn.is_healthy():
                    connection_pool.retire_connection(conn)

            except Exception as e:
                logger.error(f"Error sending to {recipient}: {str(e)}")
                connection_pool.retire_connection(conn)

        error_counter.increment()
        logger.error(f"Permanent failure: {recipient}")
        return False

    # Bulk processing with fire-and-forget
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(_process_recipient, r) for r in recipients_chunk]
        
        # Fast failure propagation
        try:
            for future in concurrent.futures.as_completed(futures, timeout=30):
                if error_counter.value >= max_errors_before_stop:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
        except KeyboardInterrupt:
            executor.shutdown(wait=False, cancel_futures=True)
            raise

    duration = time.monotonic() - start_time
    logger.info(f"""
    Batch Complete
    ==============
    Success: {success_counter.value}
    Failures: {error_counter.value}
    Duration: {duration:.1f}s
    Rate: {success_counter.value/max(duration, 0.1):.1f}/s
    """)

    return error_counter.value < max_errors_before_stop
	
# ===========================================================
# NETWORK UTILITIES (PREVIOUSLY MISSING)
# ===========================================================

def setup_socks_proxy(proxy_config):
    """Configure SOCKS proxy for socket connections with safety checks"""
    # Add default type if missing
    proxy_type = proxy_config.get('type', 'socks5').lower()
    
    proxy_type_map = {
        'socks4': socks.SOCKS4,
        'socks5': socks.SOCKS5,
        'http': socks.HTTP
    }
    
    # Get proxy type with default fallback
    socks_type = proxy_type_map.get(proxy_type, socks.SOCKS5)
    
    # Get authentication with empty defaults
    auth = proxy_config.get('auth', {})
    
    socks.set_default_proxy(
        socks_type,
        proxy_config['host'],
        proxy_config['port'],
        username=auth.get('user', ''),
        password=auth.get('pass', '')
    )
    socket.socket = socks.socksocket

def get_socks5_proxies(config):
    """Safer proxy loading with validation"""
    proxies = []
    if config.get('use_sock', False):
        # Handle different spelling variations
        proxy_keys = ['socks5_proxies', 'sock5_proxies', 'proxies']
        for key in proxy_keys:
            if key in config:
                proxies = config[key]
                break
                
        valid_proxies = []
        for proxy in proxies:
            # Add default type if missing
            if 'type' not in proxy:
                proxy['type'] = 'socks5'
            if validate_proxy(proxy):
                valid_proxies.append(proxy)
        
        logger.info(f"Loaded {len(valid_proxies)} valid proxies")
        return valid_proxies
    return []

def validate_proxy(proxy):
    """More robust proxy validation"""
    try:
        # Set default values for missing fields
        proxy_type = proxy.get('type', 'socks5').lower()
        host = proxy['host']
        port = proxy['port']
        auth = proxy.get('auth', {})
        
        # Map proxy type
        proxy_type_map = {
            'socks4': socks.SOCKS4,
            'socks5': socks.SOCKS5,
            'http': socks.HTTP
        }
        socks_type = proxy_type_map.get(proxy_type, socks.SOCKS5)
        
        # Test connection
        socks.set_default_proxy(
            socks_type,
            host,
            port,
            username=auth.get('user', ''),
            password=auth.get('pass', '')
        )
        with socks.socksocket() as s:
            s.settimeout(10)
            s.connect(('8.8.8.8', 53))
        return True
    except Exception as e:
        logger.error(f"Proxy validation failed: {str(e)}")
        return False

def create_smtp_connection(smtp_config, use_sock=False, current_proxy=None, timeout=15):
    """Ultra-fast connection setup"""
    host = smtp_config['smtp_server']
    port = smtp_config.get('port', 25)
    
    # Bypass EHLO for speed
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            server.docmd("STARTTLS") if port == 587 else None

        # Immediate authentication
        if smtp_config.get('username'):
            server.login(smtp_config['username'], smtp_config['password'])
            
        return server
    except Exception as e:
        logger.debug(f"Connection failed: {str(e)}")
        return None
		
# ===========================================================
# MAIN EXECUTION FLOW
# ===========================================================
def run_in_threads(config, max_retries=3, max_errors_before_stop=1000, num_threads=50, links_list=[]):
    # Initialization and validation
    recipients = read_recipients(config.get('recipient_list_file'))
    total_recipients = len(recipients)
    
    if not recipients:
        logger.error(f"{Fore.RED}No recipients found!{Style.RESET_ALL}")
        return

    # Connection setup
    smtp_servers = config.get('smtp_servers', [])
    proxies = get_socks5_proxies(config) if config.get('use_sock', False) else None
    
    # High-performance connection pool
    connection_pool = SMTPConnectionPool(
        smtp_configs=smtp_servers,
        proxy_list=proxies,
        max_reuse=config.get('smtp_pool', {}).get('max_reuse', 500),
        max_age=config.get('smtp_pool', {}).get('max_age', 600),
        min_connections=len(proxies)*10 if proxies else 50
    )

    # Dynamic thread scaling
    num_threads = min(
        config.get('num_threads', 100),
        len(proxies) * 20 if proxies else 100
    )
    logger.info(f"{Fore.CYAN}Using {num_threads} threads with {len(proxies or [])} proxies{Style.RESET_ALL}")

    # Bulk processing setup
    try:
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Dynamic batching based on thread count
            chunk_size = max(10, len(recipients) // (num_threads * 2))
            chunks = [recipients[i:i+chunk_size] for i in range(0, len(recipients), chunk_size)]
            
            logger.info(f"{Fore.YELLOW}Processing {len(chunks)} chunks ({chunk_size} emails/chunk){Style.RESET_ALL}")

            # Submit all tasks at once
            futures = {executor.submit(
                send_batch_emails,
                config,
                chunk,
                max_retries,
                max_errors_before_stop,
                [0],  # sent_count
                total_recipients,
                links_list,
                connection_pool,
                min(10, num_threads // 5)  # sub-threads per chunk
            ) for chunk in chunks}

            # Fast completion monitoring
            start_time = time.monotonic()
            for future in concurrent.futures.as_completed(futures, timeout=30):
                try:
                    future.result()
                    logger.debug(f"{Fore.GREEN}Chunk completed{Style.RESET_ALL}")
                except Exception as e:
                    logger.error(f"{Fore.RED}Chunk error: {str(e)}{Style.RESET_ALL}")
                
                # Early termination check
                if connection_pool.error_count >= max_errors_before_stop:
                    logger.critical(f"{Fore.RED}Maximum errors reached, terminating{Style.RESET_ALL}")
                    break

    except KeyboardInterrupt:
        logger.warning(f"{Fore.YELLOW}Shutdown signal received{Style.RESET_ALL}")
    finally:
        # Fast connection cleanup
        connection_pool.retire_all_connections()
        logger.info(f"{Fore.CYAN}Cleaned all connections{Style.RESET_ALL}")

    # Performance summary
    duration = time.monotonic() - start_time
    logger.info(f"""
    {Fore.GREEN}Campaign Complete{Style.RESET_ALL}
    ===================
    Total Recipients: {total_recipients}
    Successful sends: {connection_pool.success_count}
    Failed sends: {connection_pool.error_count}
    Total duration: {duration:.1f}s
    Rate: {connection_pool.success_count/max(duration,1):.1f} emails/sec
    """)
		
# -----------------------------------------------------------
# NEW SECTION: EXCHANGE (OWA) SENDING FUNCTIONALITY WITH THREADING
# -----------------------------------------------------------
from exchangelib import Credentials, Configuration, Account, DELEGATE, HTMLBody, Message, Mailbox, FileAttachment
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter

def setup_custom_ssl_adapter():
    """
    Set up a custom SSL adapter that ignores certificate validation.
    This is required for Exchange (OWA) sending if the server uses self-signed or invalid certs.
    """
    class CustomAdapter(NoVerifyHTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            import ssl
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            kwargs['ssl_context'] = context
            return super().init_poolmanager(*args, **kwargs)
        def proxy_manager_for(self, *args, **kwargs):
            import ssl
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            kwargs['ssl_context'] = context
            return super().proxy_manager_for(*args, **kwargs)
    BaseProtocol.HTTP_ADAPTER_CLS = CustomAdapter
    print("[*] Custom SSL adapter for Exchange has been set up.")

def send_exchange_email(recipient_email, config, links_list, owa_iter, delay, sent_count, total_recipients):
    """
    Sends one email via Exchange (OWA) for a single recipient.
    Uses the next OWA configuration from owa_iter.
    Unified placeholder logic is used for both subject and body.
    If html2pdf is enabled, a PDF is generated and attached.
    Updates the shared sent_count.
    """
    try:
        owa = next(owa_iter)
        credentials = Credentials(owa['username'], owa['password'])
        exch_config = Configuration(server=owa['server'], credentials=credentials)
        account = Account(primary_smtp_address=owa['username'], config=exch_config,
                          autodiscover=False, access_type=DELEGATE)
        subject = replace_tags(config.get("subject", ""), recipient_email, links_list)
        personalized_body = load_message_body(config.get("message_body", ""), recipient_email, 'html', links_list)
        message = Message(
            account=account,
            subject=subject,
            body=HTMLBody(personalized_body),
            to_recipients=[Mailbox(email_address=recipient_email)]
        )
        # Check if we need to generate and attach a PDF.
        if config.get("html2pdf", False):
            html_file = replace_tags(config.get("html2pdf_file", ""), recipient_email, links_list)
            if os.path.exists(html_file):
                pdf_bytes = generate_pdf_bytes_from_html(html_file, recipient_email, links_list)
                if pdf_bytes:
                    attach_name = replace_tags(config.get("html2pdf_attachment_name", ""), recipient_email, links_list)
                    attachment = FileAttachment(name=attach_name, content=pdf_bytes)
                    message.attach(attachment)
        message.send()
        with sent_count_lock:
            sent_count[0] += 1
        print(f"{Fore.CYAN}[Exchange] {sent_count[0]}/{total_recipients} sent to {recipient_email}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[Exchange] Error sending to {recipient_email}: {e}{Style.RESET_ALL}")
    finally:
        time.sleep(delay)

def send_exchange_batch(config, recipients_chunk, links_list, sent_count, total_recipients):
    import itertools
    owa_iter = itertools.cycle(config.get("exchange", {}).get("owas", []))
    delay = config.get("exchange", {}).get("sending_delay", 0.05)
    for recipient in recipients_chunk:
        send_exchange_email(recipient, config, links_list, owa_iter, delay, sent_count, total_recipients)

def run_exchange_in_threads(config, num_threads, links_list):
    recipient_file = config.get("recipient_list_file")
    recipients = read_recipients(recipient_file)
    total_recipients = len(recipients)
    print(f"{Fore.CYAN}Total Exchange recipients: {total_recipients}{Style.RESET_ALL}")
    sent_count = [0]
    slices = [recipients[i::num_threads] for i in range(num_threads)]
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for chunk in slices:
            futures.append(executor.submit(send_exchange_batch, config, chunk, links_list, sent_count, total_recipients))
        for future in futures:
            future.result()

# -----------------------------------------------------------
# 6) MAIN ENTRY POINT
# -----------------------------------------------------------
def main():
    print(f"{Fore.GREEN}Starting the script...{Style.RESET_ALL}")
    try:
        # 1. Config File Validation
        if not os.path.exists('config.json'):
            raise FileNotFoundError("config.json not found in working directory")

        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 2. Essential Config Validation
        required_keys = ['recipient_list_file', 'smtp_servers']
        if not config.get("use_exchange", False):
            for key in required_keys:
                if key not in config:
                    raise KeyError(f"Missing required config key: {key}")

        # 3. Links File Handling
        links_file = config.get("links_file")
        links_list = load_links_file(links_file)
        config['links_list'] = links_list
        if "%LINK%" in config.get("message_body", "") and not links_list:
            logger.warning(f"{Fore.YELLOW}%LINK% placeholder used but no links loaded!{Style.RESET_ALL}")

        # 4. Mode Selection with Fallback
        if config.get("use_exchange", False):
            print(f"{Fore.CYAN}Using Exchange (OWA) sending mode...{Style.RESET_ALL}")
            try:
                setup_custom_ssl_adapter()
                num_threads = min(config.get("num_threads", 12), 50)
                run_exchange_in_threads(config, num_threads, links_list)
            except Exception as e:
                logger.error(f"{Fore.RED}Exchange setup failed: {e}{Style.RESET_ALL}")
                raise
        else:
            # 5. SMTP Configuration Validation
            smtp_servers = config.get('smtp_servers', [])
            if not smtp_servers:
                logger.critical(f"{Fore.RED}No SMTP servers configured{Style.RESET_ALL}")
                return

            # 6. Parameter Sanitization
            num_emails_to_send = max(config.get("num_emails_to_send", 10), 0)
            max_retries = max(config.get("max_retries", 3), 1)
            max_errors = max(config.get("max_errors_before_stop", 5), 1)
            num_threads = min(config.get("num_threads", 1), 100)

            # 7. Proxy Handling with Validation
            proxies_list = get_socks5_proxies(config)
            if config.get('use_sock', False) and not proxies_list:
                logger.critical(f"{Fore.RED}Proxy required but none configured!{Style.RESET_ALL}")
                return

            # 8. Enhanced Connection Testing
            working_config = None
            if proxies_list:
                logger.info(f"{Fore.GREEN}Starting proxy validation...{Style.RESET_ALL}")
                valid_proxies = [p for p in proxies_list if validate_proxy(p)]
                
                if not valid_proxies:
                    logger.critical(f"{Fore.RED}All proxies failed validation!{Style.RESET_ALL}")
                    return

                logger.info(f"{Fore.GREEN}Testing SMTP connectivity through {len(valid_proxies)} valid proxies...{Style.RESET_ALL}")

                for proxy in valid_proxies:
                    for smtp_cfg in smtp_servers:
                        try:
                            if not check_network_access(
                                smtp_cfg['smtp_server'],
                                smtp_cfg.get('port', 25),
                                proxy=proxy,
                                timeout=10
                            ):
                                continue

                            server = create_smtp_connection(
                                smtp_cfg, 
                                use_sock=True,
                                current_proxy=proxy,
                                timeout=15
                            )
                            if server:
                                server.quit()
                                working_config = (proxy, smtp_cfg)
                                logger.info(f"{Fore.GREEN}Working configuration: {proxy['host']} -> {smtp_cfg['smtp_server']}{Style.RESET_ALL}")
                                break
                        except Exception as e:
                            logger.warning(f"{Fore.YELLOW}Connection failed: {e}{Style.RESET_ALL}")
                    
                    if working_config:
                        break

                if not working_config:
                    logger.critical(f"{Fore.RED}No working proxy+SMTP combinations found!{Style.RESET_ALL}")
                    return

            # 9. Enhanced Email Verification
            if config.get('verify_email', False):
                test_email = config.get('test_email')
                if not test_email:
                    logger.critical(f"{Fore.RED}Verification enabled but test_email missing!{Style.RESET_ALL}")
                    return

                logger.info(f"{Fore.CYAN}Starting full-config verification email to {test_email}...{Style.RESET_ALL}")
                
                verification_proxy = working_config[0] if working_config else None
                
                if not verify_email_delivery(test_email, config, verification_proxy):
                    logger.critical(f"{Fore.RED}Verification failed! Check:{Style.RESET_ALL}")
                    logger.critical(f"- Proxy/SMTP configuration")
                    logger.critical(f"- Authentication credentials")
                    logger.critical(f"- Network/firewall settings")
                    return
                
                logger.info(f"{Fore.GREEN}Verification successful! All systems go.{Style.RESET_ALL}")

            # 10. Main Execution with Error Handling
            try:
                run_in_threads(
                    config=config,
                    max_retries=max_retries,
                    max_errors_before_stop=max_errors,
                    num_threads=num_threads,
                    links_list=links_list
                )
            except Exception as e:
                logger.critical(f"{Fore.RED}Critical sending error: {str(e)}{Style.RESET_ALL}")
                raise

    except json.JSONDecodeError:
        logger.critical(f"{Fore.RED}Invalid JSON in config.json{Style.RESET_ALL}")
    except FileNotFoundError as e:
        logger.critical(f"{Fore.RED}{str(e)}{Style.RESET_ALL}")
    except KeyError as e:
        logger.critical(f"{Fore.RED}Configuration error: {str(e)}{Style.RESET_ALL}")
    except Exception as e:
        logger.critical(f"{Fore.RED}Critical error: {str(e)}{Style.RESET_ALL}")
        raise

if __name__ == '__main__':
    main()
