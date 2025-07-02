# RadioX Spotify Playlist App v2.0.0

🎵 **Automated RadioX to Spotify Playlist Integration with Advanced Features**

A sophisticated web application that automatically monitors RadioX (Global Player) for new songs and adds them to your Spotify playlist in real-time. Built with Flask backend and React frontend, featuring persistent caching, smart search strategies, and comprehensive monitoring.

## 🚀 **Key Features**

### **Core Functionality**
- **Real-time Song Detection**: Instant WebSocket-based song detection from RadioX
- **Smart Search Strategy**: AI-powered search optimization that learns from success rates
- **Persistent Daily Cache**: Survives backend restarts with date-aware caching
- **Live Activity Dashboard**: Real-time monitoring of backend activity and health
- **Historical Data Access**: Complete data export with email attachments

### **Advanced Monitoring**
- **Service State Management**: Pause/resume functionality with reason tracking
- **Duplicate Detection**: Automatic playlist cleanup and duplicate removal
- **Failed Search Queue**: Intelligent retry system for failed searches
- **Comprehensive Logging**: Detailed logging with filtered debug logs
- **Health Monitoring**: Real-time system health and performance tracking

### **Data Management**
- **Daily Summaries**: Beautiful HTML email summaries with detailed statistics
- **Historical Data Export**: JSON file attachments for any date (up to 7 days)
- **Cache Persistence**: Automatic date rollover and cleanup
- **Statistics Tracking**: Success rates, artist analysis, time patterns, and more

## 🏗️ **Architecture**

### **Backend (Flask + Python)**
- **Flask Web Server**: RESTful API endpoints and SSE streaming
- **Spotify API Integration**: OAuth2 authentication with refresh tokens
- **WebSocket Client**: Real-time RadioX metadata monitoring
- **Redis Integration**: Server-Sent Events for real-time frontend updates
- **SMTP Email**: Automated email notifications and summaries

### **Frontend (React + TypeScript)**
- **React 18**: Modern component-based UI
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Responsive, modern styling
- **Server-Sent Events**: Real-time data streaming
- **Admin Panel**: Comprehensive control interface

### **Data Storage**
- **Persistent Cache**: JSON-based file storage with automatic cleanup
- **Daily Archives**: Date-organized cache files
- **State Management**: Thread-safe file operations with locking

## 📋 **Prerequisites**

### **System Requirements**
- Python 3.8+
- Node.js 16+
- Redis Server
- SMTP Email Server (Gmail, Outlook, etc.)

### **API Keys & Credentials**
- Spotify API credentials (Client ID, Client Secret, Redirect URI)
- Email server credentials (SMTP settings)
- RadioX station configuration

## 🛠️ **Installation**

### **1. Clone Repository**
```bash
git clone https://github.com/yourusername/radiox-spotify-playlist-app.git
cd radiox-spotify-playlist-app
```

### **2. Backend Setup**
```bash
# Install Python dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

### **3. Frontend Setup**
```bash
cd frontend
npm install
npm run build
```

### **4. Docker Deployment (Recommended)**
```bash
# Build and run with Docker Compose
docker-compose up -d
```

## ⚙️ **Configuration**

### **Environment Variables**
```bash
# Spotify Configuration
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://localhost:8080/callback
SPOTIFY_PLAYLIST_ID=your_playlist_id

# Email Configuration
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
EMAIL_RECIPIENT=recipient@example.com

# Redis Configuration
REDIS_URL=redis://localhost:6379

# Application Settings
TIMEZONE=Europe/London
RADIOX_STATION_SLUG=radiox
MAX_PLAYLIST_SIZE=1000
CHECK_INTERVAL=30
```

### **Station Configuration**
- **RadioX**: Default station (Global Player)
- **Custom Stations**: Modify `RADIOX_STATION_SLUG` for other Global Player stations

## 🎯 **Usage**

### **Web Interface**
1. **Access Admin Panel**: Navigate to `/admin` for control interface
2. **Monitor Activity**: View real-time activity dashboard
3. **Manual Controls**: Force checks, retry failed songs, manage duplicates
4. **Historical Data**: Request data for any date via date picker

### **Daily Operations**
- **Automatic Monitoring**: Runs 24/7 with configurable time windows
- **Daily Summaries**: Automatic email summaries with statistics
- **Cache Management**: Automatic cleanup of old data (7-day retention)

### **Troubleshooting**
- **Debug Logs**: Request filtered debug logs via admin panel
- **Health Checks**: Monitor system health via `/health` endpoint
- **Manual Diagnostics**: Run comprehensive system diagnostics

## 📊 **Features in Detail**

### **Smart Search Strategy**
The app learns from search success rates to optimize future searches:
- **Artist-Specific Patterns**: Tracks success rates per artist
- **Strategy Optimization**: Prioritizes most successful search methods
- **Automatic Learning**: Continuously improves search accuracy

### **Persistent Daily Cache**
- **Date-Aware Storage**: Separate files for each day
- **Automatic Rollover**: Handles date changes seamlessly
- **Restart Survival**: Data persists through VM rebuilds
- **Cleanup Management**: Automatic removal of old cache files

### **Real-Time Monitoring**
- **Live Activity Feed**: Real-time backend activity display
- **Health Indicators**: System status and performance metrics
- **State History**: Complete service state change tracking
- **Performance Stats**: Memory usage, response times, success rates

### **Historical Data Export**
- **JSON Attachments**: Complete data export in standard format
- **Multiple Formats**: Separate files for added songs and failures
- **Rich Metadata**: Complete song details, timestamps, and analysis
- **Easy Import**: Compatible with Excel, Google Sheets, and analysis tools

## 🔧 **API Endpoints**

### **Core Endpoints**
- `GET /` - Main application interface
- `GET /status` - Current system status and statistics
- `GET /health` - System health check
- `GET /version` - Version information

### **Admin Endpoints**
- `POST /admin/force_check` - Trigger manual song check
- `POST /admin/pause_resume` - Pause/resume service
- `POST /admin/force_duplicates` - Trigger duplicate cleanup
- `POST /admin/retry_failed` - Retry failed search queue
- `POST /admin/send_debug_log` - Email debug logs
- `POST /admin/test_daily_summary` - Test daily summary
- `POST /admin/request_historical_data` - Request historical data

### **Real-Time Endpoints**
- `GET /stream` - Server-Sent Events stream
- `GET /activity` - Real-time activity data
- `GET /test_sse` - SSE connection test

## 📈 **Monitoring & Analytics**

### **Daily Statistics**
- **Success Rates**: Overall and per-artist success percentages
- **Artist Analysis**: Top artists and frequency analysis
- **Time Patterns**: Busiest hours and activity patterns
- **Decade Breakdown**: Release year analysis
- **Failure Analysis**: Detailed failure reason tracking

### **Performance Metrics**
- **Response Times**: API call performance tracking
- **Memory Usage**: System resource monitoring
- **Queue Status**: Failed search queue management
- **Cache Performance**: Storage efficiency metrics

## 🔒 **Security & Reliability**

### **Error Handling**
- **Graceful Degradation**: Continues operation during API failures
- **Retry Logic**: Intelligent retry with exponential backoff
- **Rate Limiting**: Respects API rate limits
- **Connection Recovery**: Automatic reconnection for WebSocket streams

### **Data Protection**
- **Secure Storage**: Environment variable-based credentials
- **File Locking**: Thread-safe cache operations
- **Backup Strategy**: Persistent cache with automatic cleanup
- **Error Logging**: Comprehensive error tracking and reporting

## 🚀 **Deployment**

### **Docker Deployment**
```bash
# Production deployment
docker-compose -f docker-compose.yml up -d

# Development deployment
docker-compose -f docker-compose.dev.yml up -d
```

### **Manual Deployment**
```bash
# Backend
python radiox_spotify.py

# Frontend (production)
cd frontend && npm run build && serve -s build
```

### **Cloud Deployment**
- **Oracle Cloud**: Tested and optimized for Oracle Cloud VMs
- **AWS/GCP**: Compatible with major cloud providers
- **VPS**: Works on any VPS with Docker support

## 📝 **Changelog**

### **v2.0.0 - Major Release**
- ✨ **Persistent Daily Cache**: Survives backend restarts with date-aware caching
- ✨ **Historical Data Export**: Complete data export with email attachments
- ✨ **Smart Search Strategy**: AI-powered search optimization
- ✨ **Real-Time WebSocket**: Instant song detection
- ✨ **Live Activity Dashboard**: Real-time monitoring interface
- ✨ **Enhanced Admin Panel**: Comprehensive control interface
- 🔧 **Improved Error Handling**: Better error recovery and logging
- 🎨 **Modern UI**: Redesigned frontend with Tailwind CSS

### **Previous Versions**
- **v1.x**: Basic functionality with manual controls
- **v0.x**: Initial development and testing

## 🤝 **Contributing**

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 **License**

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 **Acknowledgments**

- **Spotify API**: For playlist management capabilities
- **Global Player**: For RadioX metadata access
- **Flask**: For the robust web framework
- **React**: For the modern frontend framework
- **Tailwind CSS**: For the beautiful UI components

## 📞 **Support**

For support and questions:
- **Issues**: Create an issue on GitHub
- **Email**: Contact via the application's debug log feature
- **Documentation**: Check the inline code documentation

---

**Built with ❤️ for music lovers who want to keep their Spotify playlists fresh with the latest RadioX hits!** 