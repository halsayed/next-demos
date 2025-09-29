import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os
from dotenv import load_dotenv
import time
from tools import (
    fetch_available_models,
    create_s3_client,
    list_s3_buckets,
    list_pdf_files,
    generate_presigned_url,
    download_pdf_from_s3,
    convert_pdf_to_markdown,
    convert_markdown_to_pdf,
    upload_markdown_to_s3,
    upload_pdf_to_s3,
    translate_markdown_with_llm
)

# Load environment variables from .env file
load_dotenv()

# Initialize session state
if 's3_client' not in st.session_state:
    st.session_state.s3_client = None
if 'connection_status' not in st.session_state:
    st.session_state.connection_status = None
if 'buckets' not in st.session_state:
    st.session_state.buckets = []
if 'selected_bucket' not in st.session_state:
    st.session_state.selected_bucket = None
if 'pdf_files' not in st.session_state:
    st.session_state.pdf_files = []
if 'selected_pdfs' not in st.session_state:
    st.session_state.selected_pdfs = []
if 'selected_pdf_indices' not in st.session_state:
    st.session_state.selected_pdf_indices = []
if 'output_bucket' not in st.session_state:
    st.session_state.output_bucket = None
if 'selected_languages' not in st.session_state:
    st.session_state.selected_languages = []

# Page configuration
st.set_page_config(
    page_title="Document Translator",
    page_icon="🌐",
    layout="wide"
)

# Title and description
st.title("🌐 Document Translator")
st.markdown("Connect to your S3 account, select a bucket, and translate documents to multiple languages.")


# Sidebar for S3 credentials
st.sidebar.header("S3 Configuration")

# Show environment variable status
env_loaded = any([
    os.getenv("S3_ACCESS_KEY"),
    os.getenv("S3_SECRET_KEY"), 
    os.getenv("S3_URL")
])

if not env_loaded:
    st.sidebar.info("💡 Create a .env file to pre-fill credentials")
    st.sidebar.markdown("**Example .env file:**")
    st.sidebar.code("""
S3_ACCESS_KEY=your_key
S3_SECRET_KEY=your_secret
S3_URL=https://s3.amazonaws.com
SSL_VERIFY=false
""")

# Input fields for S3 credentials with default values from environment
s3_access_key = st.sidebar.text_input(
    "S3 Access Key",
    value=os.getenv("S3_ACCESS_KEY", ""),
    type="password",
    help="Enter your AWS S3 access key"
)

s3_secret_key = st.sidebar.text_input(
    "S3 Secret Key", 
    value=os.getenv("S3_SECRET_KEY", ""),
    type="password",
    help="Enter your AWS S3 secret key"
)

s3_url = st.sidebar.text_input(
    "S3 URL/Endpoint",
    value=os.getenv("S3_URL", ""),
    placeholder="https://s3.amazonaws.com",
    help="Enter your S3 endpoint URL (e.g., https://s3.amazonaws.com for AWS, or custom endpoint for MinIO)"
)

# SSL Verification setting
st.sidebar.subheader("🔒 SSL Settings")

# Get SSL verification setting from environment or default to True
ssl_verify_default = os.getenv("SSL_VERIFY", "true").lower() in ["true", "1", "yes"]
ssl_verify = st.sidebar.checkbox(
    "Verify SSL Certificate",
    value=ssl_verify_default,
    help="Uncheck to disable SSL certificate verification (useful for self-signed certificates or local MinIO)"
)

# Connect button
connect_button = st.sidebar.button("🔗 Connect to S3", type="primary")

st.sidebar.markdown("---")

api_endpoint = st.sidebar.text_input('API Endpoint URL', value=os.getenv('API_ENDPOINT', default='https://ai.nutanix.com/api/v1'))

# Clean up API endpoint - remove /chat/completions if present
if api_endpoint and api_endpoint.endswith('/chat/completions'):
    api_endpoint = api_endpoint[:-len('/chat/completions')]

api_key = st.sidebar.text_input('API Key', type='password', value=os.getenv('API_KEY', default=''))

# Dynamic model selection with API integration
if api_endpoint and api_key:
    # Initialize session state for cached models
    if 'cached_models' not in st.session_state:
        st.session_state.cached_models = []
        st.session_state.models_fetched = False
        st.session_state.last_endpoint = ""
        st.session_state.last_api_key = ""
    
    # Check if we need to refresh models (endpoint or key changed)
    if (st.session_state.last_endpoint != api_endpoint or 
        st.session_state.last_api_key != api_key or 
        not st.session_state.models_fetched):
        
        with st.sidebar:
            with st.spinner("Fetching available models..."):
                st.session_state.cached_models = fetch_available_models(api_endpoint, api_key)
                st.session_state.models_fetched = True
                st.session_state.last_endpoint = api_endpoint
                st.session_state.last_api_key = api_key
    
    # Use available models or fallback to default
    available_models = st.session_state.cached_models
    if available_models:
        # Default selection
        default_model = os.getenv('MODEL_NAME', default='vllm-llama-3-1')
        default_index = 0
        if default_model in available_models:
            default_index = available_models.index(default_model)
        
        # Model selection dropdown
        model_name = st.sidebar.selectbox(
            "Select Endpoint:",
            options=available_models,
            index=default_index,
            help="Choose from available endpoints"
        )
    else:
        st.sidebar.warning("No models found. Please check your API credentials.")
        model_name = os.getenv('MODEL_NAME', default='vllm-llama-3-1')
        
else:
    # Fallback when API credentials are not available
    st.sidebar.info("💡 Provide API Endpoint and API Key above to see available models")
    model_name = os.getenv('MODEL_NAME', default='vllm-llama-3-1')

temperature = st.sidebar.slider(
    "Select Temperature for Chatbot:",
    min_value=0.0,
    max_value=1.0,
    value=0.7,
    step=0.1
)


# Auto-connect if all environment variables are loaded
if env_loaded and s3_access_key and s3_secret_key and s3_url and st.session_state.connection_status != "connected":
    with st.spinner("Auto-connecting to S3..."):
        s3_client, connection_msg = create_s3_client(s3_access_key, s3_secret_key, s3_url, ssl_verify)
        
        if s3_client:
            st.session_state.s3_client = s3_client
            st.session_state.connection_status = "connected"
            
            # Test connection by listing buckets
            buckets, list_msg = list_s3_buckets(s3_client)
            
            if list_msg == "success":
                st.session_state.buckets = buckets
                st.success(f"✅ Auto-connected! Found {len(buckets)} bucket(s)")
            else:
                st.error(f"❌ Auto-connection failed: {list_msg}")
                st.session_state.connection_status = "failed"
        else:
            st.error(f"❌ Failed to auto-connect: {connection_msg}")
            st.session_state.connection_status = "failed"

# Manual connect button
if connect_button:
    # Validate inputs
    if not s3_access_key or not s3_secret_key:
        st.error("❌ Please provide both Access Key and Secret Key")
    else:
        with st.spinner("Connecting to S3..."):
            # Create S3 client with SSL verification setting
            s3_client, connection_msg = create_s3_client(s3_access_key, s3_secret_key, s3_url, ssl_verify)
            
            if s3_client:
                st.session_state.s3_client = s3_client
                st.session_state.connection_status = "connected"
                
                # Test connection by listing buckets
                buckets, list_msg = list_s3_buckets(s3_client)
                
                if list_msg == "success":
                    st.session_state.buckets = buckets
                    st.success(f"✅ Successfully connected! Found {len(buckets)} bucket(s)")
                else:
                    st.error(f"❌ Connection failed: {list_msg}")
                    st.session_state.connection_status = "failed"
            else:
                st.error(f"❌ Failed to create S3 client: {connection_msg}")
                st.session_state.connection_status = "failed"

# Display connection status
if st.session_state.connection_status == "connected":
    
    # Display buckets
    if st.session_state.buckets:
        st.subheader("📦 Select a Bucket")
        
        # Create bucket options for dropdown
        bucket_options = [bucket['Name'] for bucket in st.session_state.buckets]
        
        # Bucket selection dropdown
        selected_bucket = st.selectbox(
            "Choose a bucket to explore:",
            options=[""] + bucket_options,
            index=0,
            help="Select a bucket to view its documents"
        )
        
        # Update session state when bucket selection changes
        if selected_bucket != st.session_state.selected_bucket:
            st.session_state.selected_bucket = selected_bucket
            st.session_state.pdf_files = []
            st.session_state.selected_pdfs = []
            st.session_state.selected_pdf_indices = []
        
        
        # Load documents when a bucket is selected
        if selected_bucket:
            with st.spinner("Loading documents..."):
                pdf_files, pdf_msg = list_pdf_files(st.session_state.s3_client, selected_bucket)
                
                if pdf_msg == "success":
                    st.session_state.pdf_files = pdf_files
                    
                    if pdf_files:
                        
                        # Display PDF files as a list with checkboxes
                        st.subheader("📄 Select Documents")
                        
                        # Initialize selected files if not already set
                        if 'selected_pdf_indices' not in st.session_state:
                            st.session_state.selected_pdf_indices = []
                        
                        selected_pdf_indices = []
                        
                        # Create columns for better layout
                        col1, col2, col3 = st.columns([3, 1, 1])
                        
                        with col1:
                            st.write("**File Name**")
                        with col2:
                            st.write("**Size**")
                        with col3:
                            st.write("**Select**")
                        
                        st.markdown("---")
                        
                        # Display each PDF file with checkbox
                        for i, pdf in enumerate(pdf_files):
                            col1, col2, col3 = st.columns([3, 1, 1])
                            
                            with col1:
                                # Generate presigned URL for direct link
                                presigned_url, _ = generate_presigned_url(
                                    st.session_state.s3_client, 
                                    selected_bucket, 
                                    pdf['name']
                                )
                                
                                if presigned_url:
                                    # Make filename a clickable link
                                    st.markdown(f"📄 [{pdf['name']}]({presigned_url})")
                                else:
                                    st.write(f"📄 {pdf['name']}")
                            
                            with col2:
                                st.write(f"{pdf['size']:,} bytes")
                            with col3:
                                is_selected = st.checkbox(
                                    "Select",
                                    key=f"pdf_checkbox_{i}",
                                    value=i in st.session_state.selected_pdf_indices
                                )
                                if is_selected:
                                    selected_pdf_indices.append(i)
                        
                        # Update session state
                        st.session_state.selected_pdf_indices = selected_pdf_indices
                        
                        # Get selected PDF files
                        selected_pdfs = [pdf_files[i] for i in selected_pdf_indices]
                        st.session_state.selected_pdfs = selected_pdfs
                        
                        # Add conversion section
                        st.markdown("---")
                        
                        # Output bucket selection
                        st.subheader("📤 Select Output Bucket")
                        
                        # Create output bucket options (same as input buckets)
                        output_bucket_options = [bucket['Name'] for bucket in st.session_state.buckets]
                        
                        # Output bucket selection dropdown
                        output_bucket = st.selectbox(
                            "Choose output bucket for translated documents:",
                            options=[""] + output_bucket_options,
                            index=0,
                            help="Select a bucket where the translated documents will be uploaded"
                        )
                        
                        # Update session state when output bucket selection changes
                        if output_bucket != st.session_state.output_bucket:
                            st.session_state.output_bucket = output_bucket
                        
                        # Language selection
                        st.subheader("🌐 Select Languages")
                        
                        # Load languages from environment variable
                        languages_env = os.getenv("LANGUAGES", "")
                        if languages_env:
                            # Parse comma-separated languages and clean them
                            available_languages = [lang.strip() for lang in languages_env.split(",") if lang.strip()]
                        else:
                            # Default languages if LANGUAGES env var is not set
                            available_languages = [
                                "English", "Spanish", "French", "German", "Italian", 
                                "Portuguese", "Russian", "Chinese", "Japanese", "Korean",
                                "Arabic", "Hindi", "Dutch", "Swedish", "Norwegian"
                            ]
                        
                        if available_languages:
                            # Multi-select for languages
                            selected_languages = st.multiselect(
                                "Choose target languages for translation:",
                                options=available_languages,
                                default=st.session_state.selected_languages,
                                help="Select one or more languages to translate the documents to"
                            )
                            
                            # Update session state
                            st.session_state.selected_languages = selected_languages
                            
                            # Display selected languages
                            if selected_languages:
                                st.info(f"Selected languages: {', '.join(selected_languages)}")
                            else:
                                st.warning("Please select at least one language for translation")
                        else:
                            st.warning("No languages available. Please set the LANGUAGES environment variable with comma-separated language names.")
                            selected_languages = []
                        
                        # Convert button - disabled when no files selected, no output bucket selected, or no languages selected
                        can_convert = len(selected_pdfs) > 0 and st.session_state.output_bucket and len(selected_languages) > 0
                        
                        # Prepare help text based on selected languages
                        if can_convert:
                            help_text = f"Translate selected documents to: {', '.join(selected_languages)}"
                        else:
                            if len(selected_pdfs) == 0:
                                help_text = "Please select documents to process"
                            elif not st.session_state.output_bucket:
                                help_text = "Please select an output bucket"
                            else:
                                help_text = "Please select at least one language for translation"
                        
                        convert_button = st.button(
                            "🌐 Translate Documents",
                            type="primary",
                            disabled=not can_convert,
                            help=help_text
                        )
                        
                        if convert_button:
                            # Initialize conversion progress
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            # Create a container for displaying converted files as they're completed
                            converted_files_container = st.container()
                            
                            total_files = len(selected_pdfs)
                            total_tasks = total_files * len(selected_languages)  # Only translations (no original upload)
                            current_task = 0
                            successful_conversions = 0
                            failed_conversions = 0
                            converted_files = []  # Track successfully processed files
                            
                            for i, pdf in enumerate(selected_pdfs):
                                status_text.text(f"Processing {pdf['name']}... ({i + 1}/{total_files})")
                                
                                try:
                                    # Download PDF from S3
                                    pdf_content, download_msg = download_pdf_from_s3(
                                        st.session_state.s3_client,
                                        selected_bucket,
                                        pdf['name']
                                    )
                                    
                                    if download_msg != "success":
                                        st.error(f"Failed to download {pdf['name']}: {download_msg}")
                                        failed_conversions += 1
                                        current_task += len(selected_languages)
                                        progress = current_task / total_tasks
                                        progress_bar.progress(progress)
                                        continue
                                    
                                    # Convert PDF to Markdown (internal step)
                                    markdown_content, convert_msg = convert_pdf_to_markdown(pdf_content)
                                    
                                    if convert_msg != "success":
                                        st.error(f"Failed to process {pdf['name']}: {convert_msg}")
                                        failed_conversions += 1
                                        current_task += len(selected_languages)
                                        progress = current_task / total_tasks
                                        progress_bar.progress(progress)
                                        continue
                                    
                                    # Note: We don't upload the original PDF since it's the same as the input
                                    # We only upload translated versions
                                    
                                    # Translate to each selected language
                                    for lang in selected_languages:
                                        status_text.text(f"Translating {pdf['name']} to {lang}... ({i + 1}/{total_files})")
                                        
                                        try:
                                            # Translate markdown content
                                            translated_content, translate_msg = translate_markdown_with_llm(
                                                markdown_content,
                                                lang,
                                                api_key,
                                                api_endpoint,
                                                model_name,
                                                temperature
                                            )
                                            
                                            if translate_msg != "success":
                                                st.error(f"Failed to translate {pdf['name']} to {lang}: {translate_msg}")
                                                current_task += 1
                                                progress = current_task / total_tasks
                                                progress_bar.progress(progress)
                                                continue
                                            
                                            # Convert translated Markdown to PDF
                                            translated_pdf_content, pdf_convert_msg = convert_markdown_to_pdf(translated_content)
                                            
                                            if pdf_convert_msg != "success":
                                                st.error(f"Failed to convert {pdf['name']} translation to {lang} to PDF: {pdf_convert_msg}")
                                                current_task += 1
                                                progress = current_task / total_tasks
                                                progress_bar.progress(progress)
                                                continue
                                            
                                            # Upload translated PDF to S3 (with language suffix)
                                            translated_key, upload_msg = upload_pdf_to_s3(
                                                st.session_state.s3_client,
                                                st.session_state.output_bucket,
                                                translated_pdf_content,
                                                pdf['name'],
                                                language=lang
                                            )
                                            
                                            if upload_msg != "success":
                                                st.error(f"Failed to upload {pdf['name']} translation to {lang}: {upload_msg}")
                                                current_task += 1
                                                progress = current_task / total_tasks
                                                progress_bar.progress(progress)
                                                continue
                                            
                                            # Track the translated file
                                            translated_file_info = {
                                                'original_name': pdf['name'],
                                                'pdf_key': translated_key,
                                                'output_bucket': st.session_state.output_bucket,
                                                'language': lang
                                            }
                                            converted_files.append(translated_file_info)
                                            
                                            # Immediately display the link for the translated file
                                            with converted_files_container:
                                                # Generate presigned URL for the translated file
                                                presigned_url, _ = generate_presigned_url(
                                                    st.session_state.s3_client,
                                                    translated_file_info['output_bucket'],
                                                    translated_file_info['pdf_key']
                                                )
                                                
                                                if presigned_url:
                                                    # Create clickable link with language info
                                                    pdf_filename = translated_file_info['pdf_key'].split('/')[-1]  # Get just the filename
                                                    language_label = f" ({translated_file_info['language']})" if translated_file_info['language'] != 'Original' else ""
                                                    st.success(f"✅ **{pdf['name']}** translated to {lang}! 📄 [{pdf_filename}]({presigned_url}){language_label}")
                                                else:
                                                    # Fallback if presigned URL generation fails
                                                    language_label = f" ({translated_file_info['language']})" if translated_file_info['language'] != 'Original' else ""
                                                    st.success(f"✅ **{pdf['name']}** translated to {lang}! 📄 {translated_file_info['pdf_key']}{language_label}")
                                            
                                        except Exception as e:
                                            st.error(f"Error translating {pdf['name']} to {lang}: {str(e)}")
                                        
                                        current_task += 1
                                        progress = current_task / total_tasks
                                        progress_bar.progress(progress)
                                    
                                    successful_conversions += 1
                                    
                                except Exception as e:
                                    st.error(f"Error processing {pdf['name']}: {str(e)}")
                                    failed_conversions += 1
                                    current_task += len(selected_languages)
                                    progress = current_task / total_tasks
                                    progress_bar.progress(progress)
                            
                            # Final status
                            status_text.text("Translation completed!")
                            
                            # Summary
                            if successful_conversions > 0:
                                if selected_languages:
                                    st.success(f"🎉 Successfully processed {successful_conversions} file(s) and translated to {', '.join(selected_languages)}!")
                                else:
                                    st.success(f"🎉 Successfully processed {successful_conversions} file(s)!")
                                
                                st.markdown("---")
                                st.info("💡 All processed files have been displayed above as they were completed. You can click on the links to download them immediately.")
                                
                            if failed_conversions > 0:
                                st.warning(f"⚠️ {failed_conversions} file(s) failed to process")
                            
                            # Clear the status after a delay
                            time.sleep(2)
                            status_text.empty()
                            progress_bar.empty()
                            
                    else:
                        st.info("No documents found in this bucket")
                else:
                    st.error(f"❌ Failed to load documents: {pdf_msg}")
        else:
            pass
    
    
    else:
        st.warning("⚠️ No buckets found or unable to list buckets")

elif st.session_state.connection_status == "failed":
    st.error("🔴 Connection failed. Please check your credentials and try again.")

else:
    st.info("👈 Please enter your S3 credentials in the sidebar and click 'Connect to S3'")

# Footer
st.markdown("---")
st.markdown("**Document Translator** - A simple tool to connect to S3, select buckets, and translate documents to multiple languages")
