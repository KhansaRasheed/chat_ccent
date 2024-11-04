import streamlit as st
import tempfile
import os
import boto3
import requests
import json
from pydub import AudioSegment
from dotenv import load_dotenv
from audiorecorder import audiorecorder  

# Load environment variables from .env file
load_dotenv()

# Get environment variables
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
endpoint_name = os.getenv("SAGEMAKER_ENDPOINT_NAME")
aws_region = os.getenv("AWS_REGION")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")

# Initialize the SageMaker runtime client
client = boto3.client('sagemaker-runtime',
                      region_name=aws_region,
                      aws_access_key_id=aws_access_key_id, 
                      aws_secret_access_key=aws_secret_access_key)

# Initialize the S3 client
s3_client = boto3.client('s3',
                         region_name=aws_region,
                         aws_access_key_id=aws_access_key_id, 
                         aws_secret_access_key=aws_secret_access_key)

st.title("Accent Conversion Application")

choice = st.radio("Record your voice here or Upload your audio:", ("Record Audio", "Upload Audio"))

# Initialize variables to store the audio data
audio = None
uploaded_audio = None

# Step 2: Show the audio recorder or file uploader based on the user's choice
if choice == "Record Audio":
    st.info("Click 'Start recording' to begin and 'Stop recording' to end.")  # Provide instructions

    # Use the audiorecorder function with prompts and visualizer
    audio = audiorecorder(
        start_prompt="Start recording", 
        stop_prompt="Stop recording", 
        pause_prompt="", 
        show_visualizer=True
    )
    if len(audio) > 0:
        st.audio(audio.export().read(), format="audio/wav")  # Play back the recorded audio
        # Save the recorded audio as a WAV file
        audio.export("recorded_audio.wav", format="wav")
        st.success("Audio recorded successfully.")

elif choice == "Upload Audio":
    uploaded_audio = st.file_uploader("Upload Audio for Accent Conversion (MP3, MP4, WAV)", type=["mp3", "mp4", "wav"])
    if uploaded_audio is not None:
        st.audio(uploaded_audio)  # Play back the uploaded audio

# Helper function to convert uploaded audio to WAV if needed
# def convert_to_wav(uploaded_audio):
#     temp_wav_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    
#     if uploaded_audio.type == "audio/wav":
#         with open(temp_wav_file.name, 'wb') as f:
#             f.write(uploaded_audio.read())  # Save the uploaded WAV file
#         return temp_wav_file.name
#     elif uploaded_audio.type == "audio/mpeg":
#         audio = AudioSegment.from_mp3(uploaded_audio)
#     elif uploaded_audio.type == "audio/mp4":
#         audio = AudioSegment.from_file(uploaded_audio, format="mp4")
#     else:
#         st.error(f"Unsupported audio format: {uploaded_audio.type}")
#         return None

#     audio.export(temp_wav_file.name, format="wav")
    
#     return temp_wav_file.name

def convert_to_wav(uploaded_audio):
    temp_wav_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    
    # Check the MIME type and handle the conversion based on the format
    if uploaded_audio.type == "audio/wav":
        with open(temp_wav_file.name, 'wb') as f:
            f.write(uploaded_audio.read())  # Save the uploaded WAV file
        return temp_wav_file.name
    elif uploaded_audio.type == "audio/mpeg":
        audio = AudioSegment.from_mp3(uploaded_audio)
    elif uploaded_audio.type == "video/mp4" or uploaded_audio.type == "audio/mp4":
        # Extract the audio from the .mp4 file
        audio = AudioSegment.from_file(uploaded_audio, format="mp4")
    else:
        st.error(f"Unsupported audio format: {uploaded_audio.type}")
        return None

    # Export the audio to WAV format
    audio.export(temp_wav_file.name, format="wav")
    
    return temp_wav_file.name


def upload_to_s3(file_path, bucket_name, file_key):
    """Uploads a file to the specified S3 bucket."""
    try:
        with open(file_path, "rb") as file:
            s3_client.upload_fileobj(file, bucket_name, file_key)
        s3_url = f's3://{bucket_name}/{file_key}'
        return s3_url
    except Exception as e:
        st.error(f"Failed to upload to S3: {str(e)}")
        return None

# Accent selection
accent = st.selectbox(
    "Select Accent:",
    ["British", "American"]
)

# Map the selected accent to the corresponding language code
language_mapping = {
    "British": "en-br",
    "American": "en-us"
}

language = language_mapping[accent]

# Conversion button and logic
if st.button("Convert Accent"):
    if uploaded_audio is not None or audio is not None:
        if audio is not None:
            # Save the recorded audio as a WAV file
            wav_audio_path = "recorded_audio.wav"

        elif uploaded_audio is not None:
            with st.spinner("Converting audio to WAV format..."):
                wav_audio_path = convert_to_wav(uploaded_audio)

        if wav_audio_path:
            s3_object_name = f"input-audio/{os.path.basename(wav_audio_path)}"

            with st.spinner("Uploading audio..."):
                s3_url = upload_to_s3(wav_audio_path, s3_bucket_name, s3_object_name)

            if s3_url:
                st.success(f"Audio uploaded.")

                # Create the JSON payload with both the audio URL and selected language
                payload = {
                    "audio_url": s3_url,
                    "language": language
                }

                with st.spinner("Processing..."):
                    try:
                        # Invoke the SageMaker endpoint with the updated payload
                        response = client.invoke_endpoint(
                            EndpointName=endpoint_name,
                            ContentType='application/json',
                            Body=json.dumps(payload)
                        )

                        result = response['Body'].read().decode('utf-8').strip()

                        if result.startswith('"') and result.endswith('"'):
                            result = result[1:-1]

                        st.write("Converted audio:", result)

                        if result.startswith('s3://'):
                            s3_url_parts = result.replace("s3://", "").split("/")
                            result_bucket_name = s3_url_parts[0]
                            result_object_key = "/".join(s3_url_parts[1:])

                            presigned_url = s3_client.generate_presigned_url(
                                'get_object',
                                Params={'Bucket': result_bucket_name, 'Key': result_object_key},
                                ExpiresIn=3600
                            )

                            st.audio(presigned_url, format="audio/wav")
                            st.success("Audio conversion complete!")

                            audio_data = requests.get(presigned_url).content
                            st.download_button("Download Converted Audio", audio_data, file_name="converted_voice.wav")
                        else:
                            st.error("Invalid response format from SageMaker. Expected an S3 URL.")
                    except Exception as e:
                        st.error(f"Error invoking SageMaker endpoint: {str(e)}")
            else:
                st.error("Failed to upload audio to S3.")
        else:
            st.error("Failed to convert audio to WAV.")
    else:
        st.error("Please upload or record an audio file.")