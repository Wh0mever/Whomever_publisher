# 🚀 Telegram Autoposting Bot

## 📢 Latest Updates

### 📦 Bulk Groups
- Create groups of channels for easier management
- Send posts to multiple channels with one click
- Flexible group editing and management
- Smart group selection system
- Automatic group status tracking

### 🤖 Automated Posts
- Schedule posts for daily sending
- Multiple sending times per day
- Smart account rotation
- Cached media files for faster sending
- Real-time notifications about successful sends
- Full control over automated posts:
  - Edit content anytime
  - Modify groups and accounts
  - Adjust schedule
  - Pause/resume posting

## 🌟 Key Features

### 👥 Account Management
- ✅ Add and authorize new accounts
- ✅ Two-factor authentication (2FA) support
- ✅ Status management (active/frozen)
- ✅ Secure session storage with encryption
- ✅ Activity monitoring for each account

### 📢 Group Management
- ✅ Smart group addition via message forwarding
- ✅ Automatic accessibility and permissions check
- ✅ Support for public and private groups
- ✅ Automatic group information updates
- ✅ Group status monitoring system

### 📝 Post Creation and Sending
- ✅ Support for all media types:
  - 📄 Formatted text
  - 🖼️ Photos (up to 50MB)
  - 🎥 Videos (up to 50MB)
  - 📎 Documents and files
- ✅ Multiple group selection for posting
- ✅ Account selection for distribution
- ✅ Real-time sending progress

### ⚡ Posting Automation
- ✅ Automated post creation
- ✅ Flexible sending schedule:
  - 🕒 Daily sending at specified times
  - 📅 Multiple time slots
  - 🔄 Account rotation
- ✅ Automated post management:
  - 📝 Content editing
  - 👥 Group modification
  - 👤 Account modification
  - ⏰ Schedule adjustment

## 🎯 Quick Button Guide

### 📝 Create Post
- Send text/photo/video/file
- Select groups with checkmarks
- Select accounts with checkmarks
- Click "Confirm" - post sends immediately

### ⏰ Scheduled Post
- Same as "Create Post"
- At the end, enter sending time:
  - Specific time: 25.03 15:30
  - Relative time: +30 (in 30 minutes)

### 📋 Posts List
Shows scheduled posts:
- 📝 View post details
- ▶️ Send now
- ❌ Cancel sending

### 🔍 Group Check
Checks all groups for availability:
- ✅ Available
- ❌ Unavailable
- ⚠️ Needs permissions

### 👥 Group Management
- ➕ Add group: forward any message from group
- 📋 Groups list: all your groups
- ❌ Delete group: select group to delete

### 👤 Account Management
- ➕ Add account:
  1. Enter phone number
  2. Enter Telegram code
  3. If 2FA enabled - enter password
- 📊 Account status:
  - ❄️ Freeze account
  - 🌡 Unfreeze account
  - ❌ Delete account

### ⚙️ Settings
- ⏱ Interval between posts (in seconds)
- 🔄 Number of threads (1-5)
- 🔁 Number of retries on error (1-5)

## 💡 Useful Combinations

1. Quick Mass Mailing:
   - Create post
   - Select all groups
   - Select multiple accounts
   - Bot will distribute load

2. Scheduled Post Series:
   - Create several scheduled posts
   - Set times with intervals
   - Bot will send everything on schedule

3. Safe Mailing:
   - Set interval 30-60 seconds
   - Use 2-3 threads
   - Distribute groups between accounts

4. Pre-mailing Check:
   - First check groups
   - Check account status
   - Then start mailing

5. Mailing Management:
   - In posts list you can:
     - Cancel unnecessary
     - Send urgent immediately
     - Check sending status

## 🛡️ Security

### 🔐 Data Protection
- All sessions and sensitive data encryption
- Secure API key storage
- Unauthorized access protection
- Backup system
- Automatic temporary file deletion
- Session interception protection

### 🛑 Anti-spam Protection
- Smart sending intervals
- Account rotation
- Block monitoring
- Automatic freezing on suspicious activity
- Suspicious activity warning system
- Mass blocking protection

## 📊 Monitoring and Statistics

### 📈 Activity Tracking
- Per-account sending statistics:
  - Number of successful sends
  - Number of errors
  - Last activity time
  - Activity status
- Group usage history:
  - Posting frequency
  - Sending success
  - Availability status
- Sending success analysis:
  - Successful sends percentage
  - Error types
  - Optimization recommendations

### 📋 Logging
- Detailed operation logs:
  - User actions
  - System events
  - Errors and warnings
- Separate component logs:
  - Accounts
  - Groups
  - Post sending
  - Automation
- Size-based log rotation
- Easy access to history
- Log filtering and search
- Log export in various formats

## 🔧 Installation and Setup

### 📥 Requirements
- Python 3.8 or higher
- 512MB RAM (1GB recommended)
- 1GB free space
- Stable internet connection
- Registered Telegram application
- Telegram API access

### ⚙️ Installation Process
```bash
# 1. Clone repository
git clone https://github.com/yourusername/telegram-autoposting-bot.git
cd telegram-autoposting-bot

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure settings
# Create config.py and add necessary parameters:
# - BOT_TOKEN
# - API_ID
# - API_HASH
# - Other settings

# 5. Start the bot
python bot.py
```

### 📱 Initial Setup
1. Getting necessary data:
   - Create bot via @BotFather
   - Get API_ID and API_HASH from my.telegram.org
   - Configure parameters in config.py

2. Bot setup:
   - Start bot with /start command
   - Add first account
   - Add groups
   - Configure sending parameters

## 🔄 Working Process

### 1. Preparation
1. Add at least one account
2. Add desired groups
3. Configure intervals and threads
4. Check group availability

### 2. Creating a Post
1. Choose post type (regular/scheduled/automated)
2. Send content to bot
3. Select target groups
4. Select accounts for sending
5. Confirm action

### 3. Sending Process
1. Bot shows sending progress:
   - Completion percentage
   - Current account
   - Current group
   - Number of successful sends
   - Number of errors
2. On completion shows summary:
   - Total execution time
   - Number of successful sends
   - Number of errors
   - Used accounts

### 4. Monitoring and Management
- Track sending status
- Ability to cancel process
- View logs and errors
- Manage post queue

## 🆘 Troubleshooting

### 🔍 Common Issues and Solutions
1. **Authorization Error**
   - Check phone number correctness
   - Ensure code validity
   - Check account status
   - Try re-authorization

2. **Group Unavailability**
   - Check access rights
   - Verify group existence
   - Check posting permissions
   - Try re-subscribing

3. **Sending Errors**
   - Check internet connection
   - Verify account activity
   - Check media file sizes
   - Increase intervals between sends

### 🛠 Diagnostics
1. Check logs in `logs/` folder
2. Verify settings correctness
3. Check account status
4. Perform group check
5. If necessary:
   - Restart bot
   - Re-authorize account
   - Update group data

## 📞 Support and Updates

### 🔄 Bot Updates
1. Create data backup:
   - Database
   - Configuration
   - Account sessions
2. Execute `git pull`
3. Update dependencies
4. Restart bot

### 📧 Technical Support
- Log analysis
- Problem diagnostics
- Data recovery
- Setup consultation
- Optimization help
- Security recommendations

## 📄 License
MIT License - free use with attribution

## 🔗 Useful Links
- [Telegram API](https://core.telegram.org/api)
- [Python Telegram Bot](https://python-telegram-bot.org/)
- [Telethon Documentation](https://docs.telethon.dev/)
- [Aiogram Documentation](https://docs.aiogram.dev/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Python Documentation](https://docs.python.org/)
- [Git Documentation](https://git-scm.com/doc)
- [Virtual Environment Guide](https://docs.python.org/3/tutorial/venv.html) 