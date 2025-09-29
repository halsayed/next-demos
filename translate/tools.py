import json
import requests
import streamlit as st
import logging
import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.config import Config
import urllib3
import tempfile
import shutil
from markdrop import markdrop, MarkDropConfig
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from markdown_pdf import MarkdownPdf, Section


logging.basicConfig(level=os.getenv('LOG_LEVEL', default='INFO'))
logger = logging.getLogger(__name__)


def fetch_available_models(api_endpoint, api_key):
    """Fetch available models from the OpenAI endpoint"""
    try:
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        # Construct the models endpoint URL
        if api_endpoint.endswith('/'):
            models_url = f"{api_endpoint}models"
        else:
            models_url = f"{api_endpoint}/models"
        
        response = requests.get(models_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            models = [model['id'] for model in data.get('data', [])]
            # Sort models alphabetically for better UX
            models.sort()
            return models
        elif response.status_code == 401:
            st.error("Authentication failed. Please check your API key.")
            return []
        elif response.status_code == 404:
            st.error("Models endpoint not found. Please check your API endpoint URL.")
            return []
        else:
            st.error(f"Failed to fetch models: {response.status_code} - {response.text}")
            return []
            
    except requests.exceptions.ConnectionError:
        st.error("Connection failed. Please check your API endpoint URL and internet connection.")
        return []
    except requests.exceptions.Timeout:
        st.error("Request timed out. Please try again.")
        return []
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {str(e)}")
        return []
    except json.JSONDecodeError as e:
        st.error(f"Error parsing response: {str(e)}")
        return []
    except Exception as e:
        st.error(f"Unexpected error: {str(e)}")
        return []


def create_s3_client(access_key, secret_key, endpoint_url, verify_ssl=True):
    """Create and return an S3 client with the provided credentials."""
    try:
        # Disable SSL warnings if SSL verification is disabled
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Determine if we should use SSL based on endpoint URL
        use_ssl = True
        if endpoint_url:
            use_ssl = endpoint_url.startswith('https://')
        
        # Create boto3 configuration
        config = Config(
            retries={'max_attempts': 3},
            connect_timeout=60,
            read_timeout=60
        )
        
        # Create S3 client with SSL verification setting
        s3_client = boto3.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint_url if endpoint_url else None,
            use_ssl=use_ssl,
            verify=verify_ssl,
            config=config
        )
        return s3_client, "success"
    except Exception as e:
        return None, str(e)


def list_s3_buckets(s3_client):
    """List all S3 buckets and return the result."""
    try:
        response = s3_client.list_buckets()
        buckets = response.get('Buckets', [])
        return buckets, "success"
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidAccessKeyId':
            return [], "Invalid Access Key ID"
        elif error_code == 'SignatureDoesNotMatch':
            return [], "Invalid Secret Key"
        else:
            return [], f"AWS Error: {error_code}"
    except NoCredentialsError:
        return [], "No credentials provided"
    except Exception as e:
        return [], f"Error: {str(e)}"


def list_pdf_files(s3_client, bucket_name):
    """List all PDF files in the specified S3 bucket."""
    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        pdf_files = []
        
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                if key.lower().endswith('.pdf'):
                    pdf_files.append({
                        'name': key,
                        'size': obj['Size'],
                        'last_modified': obj['LastModified']
                    })
        
        return pdf_files, "success"
    except ClientError as e:
        error_code = e.response['Error']['Code']
        return [], f"AWS Error: {error_code}"
    except Exception as e:
        return [], f"Error: {str(e)}"


def generate_presigned_url(s3_client, bucket_name, object_key, expiration=3600):
    """Generate a presigned URL for S3 object access."""
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_key},
            ExpiresIn=expiration
        )
        return url, "success"
    except ClientError as e:
        return None, f"Error generating presigned URL: {e}"
    except Exception as e:
        return None, f"Error: {str(e)}"


def download_pdf_from_s3(s3_client, bucket_name, object_key):
    """Download PDF file from S3 and return the content."""
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        return response['Body'].read(), "success"
    except ClientError as e:
        return None, f"Error downloading PDF: {e}"
    except Exception as e:
        return None, f"Error: {str(e)}"


def convert_pdf_to_markdown(pdf_content):
    """Convert PDF content to Markdown using markdrop library."""
    try:
        # Create a temporary file to store the PDF
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
            temp_pdf.write(pdf_content)
            temp_pdf_path = temp_pdf.name
        
        # Create a temporary directory for the markdown output
        temp_dir = tempfile.mkdtemp()
        
        # Configure markdrop
        config = MarkDropConfig(
            image_resolution_scale=2.0,
            log_level='INFO',
            log_dir=os.path.join(temp_dir, 'logs'),
            excel_dir=os.path.join(temp_dir, 'excel_tables')
        )
        
        # Convert PDF to Markdown
        markdrop(temp_pdf_path, temp_dir, config)
        
        # Find the generated markdown file
        markdown_files = [f for f in os.listdir(temp_dir) if f.endswith('.md')]
        
        if not markdown_files:
            return None, "No markdown file generated"
        
        # Read the markdown content
        markdown_path = os.path.join(temp_dir, markdown_files[0])
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Clean up temporary files
        os.unlink(temp_pdf_path)
        shutil.rmtree(temp_dir)
        
        return markdown_content, "success"
    except Exception as e:
        # Clean up temporary files in case of error
        try:
            if 'temp_pdf_path' in locals():
                os.unlink(temp_pdf_path)
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir)
        except:
            pass
        return None, f"Error converting PDF to Markdown: {str(e)}"


def get_system_prompt(language):
    """Generate a system prompt for translating markdown content to the target language."""
    return f"""You are a professional translator. Your task is to translate the provided markdown text to {language}.

IMPORTANT INSTRUCTIONS:
1. Translate all text content to {language} while preserving the original markdown formatting
2. DO NOT translate or modify:
   - Code blocks (text within ``` or ```language blocks)
   - URLs (http://, https://, www., etc.)
   - File paths and technical identifiers
   - Markdown syntax (**, *, #, [], (), etc.)
   - Numbers, dates, and technical measurements
3. Preserve all markdown structure including headers, lists, tables, links, and code blocks
4. Maintain the same markdown formatting as the original
5. Only translate the actual text content, not the markdown syntax
6. If a word or phrase is already in {language} or is a proper noun, leave it unchanged
7. CRITICAL: For tables, maintain the exact table structure with proper alignment:
   - Keep the same number of columns and rows
   - Preserve table headers and cell alignment
   - Maintain pipe characters (|) and table separators (---)
   - Only translate the text content within table cells, not the table structure
   - Ensure table formatting remains valid markdown

Return only the translated markdown content without any additional explanations or comments."""


def translate_markdown_with_llm(markdown_content, language, api_key, api_endpoint, model_name, temperature=0.3):
    """Translate markdown content to target language using LLM."""
    try:
        # Initialize the LLM
        llm = ChatOpenAI(
            openai_api_key=api_key,
            model_name=model_name,
            openai_api_base=api_endpoint,
            temperature=temperature
        )
        
        # Get system prompt for the target language
        system_prompt = get_system_prompt(language)
        
        # Prepare messages
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=markdown_content)
        ]
        
        # Generate translation
        response = llm(messages)
        
        return response.content, "success"
        
    except Exception as e:
        return None, f"Error translating to {language}: {str(e)}"


def convert_markdown_to_pdf(markdown_content):
    """Convert markdown content to PDF using markdown-pdf library."""
    try:
        # Create a temporary file for the PDF output
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
            temp_pdf_path = temp_pdf.name
        
        # Initialize MarkdownPdf
        pdf = MarkdownPdf()
        
        # Clean and prepare the markdown content
        # Ensure it starts with a proper heading structure
        lines = markdown_content.strip().split('\n')
        
        # Find the first heading and ensure it's level 1
        first_heading_found = False
        processed_lines = []
        
        for line in lines:
            if line.strip().startswith('#'):
                if not first_heading_found:
                    # Make sure the first heading is level 1
                    if not line.strip().startswith('# '):
                        # Convert to level 1 heading
                        line = '# ' + line.strip().lstrip('#').strip()
                    first_heading_found = True
                processed_lines.append(line)
            else:
                processed_lines.append(line)
        
        # If no heading was found, add a default one
        if not first_heading_found:
            processed_lines.insert(0, "# Document")
            processed_lines.insert(1, "")  # Add empty line after heading
        
        # Join the processed lines
        processed_markdown = '\n'.join(processed_lines)
        
        # Add a section with the processed markdown content
        pdf.add_section(Section(processed_markdown))
        
        # Save the PDF to the temporary file
        pdf.save(temp_pdf_path)
        
        # Read the generated PDF content
        with open(temp_pdf_path, 'rb') as f:
            pdf_content = f.read()
        
        # Clean up temporary files
        os.unlink(temp_pdf_path)
        
        return pdf_content, "success"
    except Exception as e:
        # Clean up temporary files in case of error
        try:
            if 'temp_pdf_path' in locals():
                os.unlink(temp_pdf_path)
        except:
            pass
        return None, f"Error converting markdown to PDF: {str(e)}"


def upload_pdf_to_s3(s3_client, bucket_name, pdf_content, original_key, language=None):
    """Upload PDF content to S3 with .pdf extension and optional language suffix."""
    try:
        # Generate new key with .pdf extension
        base_name = os.path.splitext(original_key)[0]
        
        if language:
            # Add language suffix to filename
            pdf_key = f"{base_name}_{language}.pdf"
        else:
            pdf_key = f"{base_name}.pdf"
        
        # Upload PDF content
        s3_client.put_object(
            Bucket=bucket_name,
            Key=pdf_key,
            Body=pdf_content,
            ContentType='application/pdf'
        )
        
        return pdf_key, "success"
    except ClientError as e:
        return None, f"Error uploading PDF: {e}"
    except Exception as e:
        return None, f"Error: {str(e)}"


def upload_markdown_to_s3(s3_client, bucket_name, markdown_content, original_key, language=None):
    """Upload markdown content to S3 with .md extension and optional language suffix."""
    try:
        # Generate new key with .md extension
        base_name = os.path.splitext(original_key)[0]
        
        if language:
            # Add language suffix to filename
            markdown_key = f"{base_name}_{language}.md"
        else:
            markdown_key = f"{base_name}.md"
        
        # Upload markdown content
        s3_client.put_object(
            Bucket=bucket_name,
            Key=markdown_key,
            Body=markdown_content.encode('utf-8'),
            ContentType='text/markdown'
        )
        
        return markdown_key, "success"
    except ClientError as e:
        return None, f"Error uploading markdown: {e}"
    except Exception as e:
        return None, f"Error: {str(e)}"

