#!/bin/bash

# Install FFmpeg
apt-get update && apt-get install -y ffmpeg

# Start the bot
python disapp.py 
