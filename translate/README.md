# S3 Bucket Manager

A Streamlit application that allows you to connect to S3-compatible storage services and list all available buckets.

## Features

- 🔐 Secure credential input (S3 Access Key, Secret Key, and Endpoint URL)
- 🔗 One-click connection to S3 services
- 📦 List all available buckets
- 📊 Display bucket information including creation dates
- 🛡️ Error handling for invalid credentials or connection issues
- 🎨 Clean and intuitive user interface

## Supported S3 Services

- AWS S3
- MinIO
- Any S3-compatible storage service

## Installation

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. (Optional) Create a `.env` file for default credentials:
```bash
cp .env.example .env
# Edit .env with your actual S3 credentials
```

## Usage

1. Run the Streamlit app:
```bash
streamlit run app.py
```

2. Open your browser and navigate to the provided URL (usually `http://localhost:8501`)

3. Enter your S3 credentials in the sidebar (or they will be pre-filled if you created a `.env` file):
   - **S3 Access Key**: Your S3 access key
   - **S3 Secret Key**: Your S3 secret key  
   - **S3 URL/Endpoint**: The S3 endpoint URL (e.g., `https://s3.amazonaws.com` for AWS)

4. Click "Connect to S3" to establish the connection

5. View your buckets in the main area

## Configuration

### For AWS S3
- **S3 URL**: `https://s3.amazonaws.com` (or leave empty for default)
- Use your AWS Access Key ID and Secret Access Key

### For MinIO
- **S3 URL**: `http://your-minio-server:9000` (or your MinIO endpoint)
- Use your MinIO access key and secret key
- **SSL Verification**: Set to `false` if using self-signed certificates

## SSL Configuration

The app includes SSL verification settings that can be configured:

### SSL Verification Options
- **Enabled (default)**: Verifies SSL certificates - recommended for production
- **Disabled**: Skips SSL certificate verification - useful for:
  - Local MinIO instances with self-signed certificates
  - Development environments
  - Internal S3-compatible services

### Configuration Methods

1. **Via UI**: Use the "Verify SSL Certificate" checkbox in the sidebar
2. **Via Environment**: Set `SSL_VERIFY=false` in your `.env` file
3. **Via Code**: The setting defaults to `true` for security

### Security Warning
⚠️ **Only disable SSL verification in trusted environments** (local development, internal networks). Disabling SSL verification in production can expose your data to man-in-the-middle attacks.

## Environment Variables

You can create a `.env` file in the same directory as `app.py` to pre-fill the S3 credentials:

```bash
# .env file
S3_ACCESS_KEY=your_access_key_here
S3_SECRET_KEY=your_secret_key_here
S3_URL=https://s3.amazonaws.com
SSL_VERIFY=true
```

The app will automatically load these values and pre-fill the input fields. This is especially useful for development and when you don't want to manually enter credentials each time.

## Security Note

This application stores credentials only in the browser session and does not persist them. Credentials are cleared when you refresh the page or close the browser. The `.env` file is for convenience and should be kept secure and not committed to version control.
