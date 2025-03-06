# Telegram Auto-Posting Bot 🚀

A powerful multi-threaded bot for automatically sending messages to Telegram groups with multi-account support and advanced posting management features.

## 📥 Installation and Setup

### 1. Clone the Repository
```bash
git clone https://github.com/wh0mever/Whomever_publisher.git
cd Whomever_publisher
```

### 2. Create a Virtual Environment

For Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

For Linux/Mac:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Settings
Create a `config.py` file with the following parameters:
```python
from pathlib import Path

# Basic Settings
BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
DATABASE_PATH = BASE_DIR / "database" / "bot.db"

# Create Directories
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Bot Settings
BOT_TOKEN = "YOUR_BOT_TOKEN"  # Obtain from @BotFather
API_ID = 12345678  # Obtain from my.telegram.org
API_HASH = "your_api_hash"  # Obtain from my.telegram.org

# Posting Settings
DEFAULT_DELAY = 30  # Delay between posts (sec)
MAX_THREADS = 5  # Maximum parallel threads
MAX_RETRIES = 3  # Retry attempts on failure
```

### 5. Obtain Required Credentials

1. **Create a bot and get a token:**
   - Open @BotFather in Telegram
   - Send the command `/newbot`
   - Follow the instructions to create a bot
   - Copy the received token into `config.py`

2. **Get API_ID and API_HASH:**
   - Go to https://my.telegram.org/apps
   - Log into your account
   - Create a new application
   - Copy the API_ID and API_HASH into `config.py`

### 6. Start the Bot
```bash
python bot.py
```

### 7. Initial Setup
1. Open your bot in Telegram
2. Send the command `/start`
3. Add at least one account
4. Add the required groups
5. Configure posting settings

## 📱 Bot Main Menu

### 👤 Account Management
- **Add Account**
  - Press "👤 Add Account"
  - Enter the phone number in international format
  - Enter the confirmation code from Telegram
  - Enter the 2FA password if required
  - The account will be added to the system

- **Account Status**
  - Displays a list of all added accounts
  - Shows for each account:
    - Phone number
    - Status (active/frozen)
    - Last used date
  - Available actions:
    - ❄️ Freeze account (temporarily disable)
    - 🌡 Unfreeze account (reactivate)
    - ❌ Remove account from system

### 👥 Group Management
- **Add Group**
  - Press "➕ Add Group"
  - Forward any message from the group
  - The bot automatically detects:
    - Group ID
    - Name
    - Username (if available)
    - Group type (public/private)

- **Group List**
  - Displays all added groups
  - Shows for each group:
    - Name
    - Username/link
    - Access status
  - Option to delete groups

- **Group Check**
  - Automatic availability check for all groups
  - Checks:
    - Group existence
    - Posting permissions
    - Subscription possibility
  - Updates group statuses in the database

### 📢 Posting Management
- **New Post**
  - Create an instant post
  - Supported content types:
    - 📝 Formatted text
    - 🖼 Images
    - 🎥 Videos
    - 📎 Documents/files
  - Posting process:
    1. Send content to the bot
    2. Select target groups
    3. Select accounts for posting
    4. Confirm sending

- **Scheduled Post**
  - Create a post with delayed publishing
  - Two time formats:
    - Specific date and time (25.03 15:30)
    - Relative time (+30 minutes)
  - Same content types as regular posts
  - Additional options:
    - View scheduled time
    - Cancel scheduled post
    - Send immediately

- **Post List**
  - Displays all scheduled posts
  - Shows for each post:
    - Content
    - Posting time
    - Selected groups
    - Selected accounts
  - Post actions:
    - 📝 View details
    - ▶️ Send now
    - ❌ Cancel sending

### ⚙️ Settings
- **Post Interval**
  - Set delay between posts
  - Recommended interval: 30-60 seconds
  - Protection against spam blocks
  - Applies to all accounts

- **Thread Count**
  - Configure parallel posting
  - From 1 to 5 threads
  - Optimal value: 2-3 threads
  - Affects posting speed

- **Retry Attempts**
  - Set retry attempts on failure
  - Default: 3 attempts
  - Increases reliability
  - Auto-retry on errors

## 🔄 Workflow

### 1. Preparation
1. Add at least one account
2. Add required groups
3. Configure intervals and threads
4. Check group availability

### 2. Creating a Post
1. Choose post type (instant/scheduled)
2. Send content to the bot
3. Select target groups
4. Select accounts for sending
5. Confirm the action

### 3. Sending Process
1. The bot shows posting progress:
   - Completion percentage
   - Current account
   - Current group
   - Number of successful sends
   - Number of errors
2. Upon completion, displays results:
   - Total execution time
   - Number of successful sends
   - Number of errors
   - Accounts used

### 4. Monitoring and Management
- Track posting status
- Cancel process if needed
- View logs and errors
- Manage post queue

## 🛡 Security and Restrictions

### Account Protection
- Encrypted sessions
- Two-factor authentication support
- Auto-freeze on suspicious activity
- Spam block protection

### Limits and Restrictions
- Media file size: up to 50MB
- Max threads: 5
- Minimum interval: 10 seconds
- Max retries: 5

### Usage Recommendations
- Do not set very short intervals
- Use different accounts for large postings
- Regularly check group availability
- Monitor account statuses

## 📊 Statistics and Logs

### Logging
- All actions are logged
- Separate logs for each component:
  - Accounts
  - Groups
  - Post sending
  - Errors
- Log rotation by size

### Statistics
- Number of successful posts
- Number of errors
- Execution time
- Account and group status

## 🆘 Troubleshooting

### Common Issues
1. **Authorization Error**
   - Check phone number correctness
   - Ensure the code is up to date
   - Verify account status

2. **Group Inaccessibility**
   - Check posting permissions
   - Ensure group existence
   - Verify posting ability

3. **Sending Errors**
   - Check internet connection
   - Ensure account is active
   - Check media file sizes

## 🔄 Updates and Support

### Updating the Bot
1. Backup data
2. Run `git pull`
3. Update dependencies
4. Restart the bot

### Technical Support
- Log inspection
- Problem diagnostics
- Data recovery
- Configuration consultation

## 📝 License

MIT License - Free use with attribution

