import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime
import requests
import yt_dlp
import asyncio
from urllib.parse import urlparse
import json

# Initialize bot with command prefix '!'
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)  # Disable default help

# FFmpeg path configuration
def find_ffmpeg():
    # List of possible FFmpeg paths
    possible_paths = [
        os.path.join(os.getcwd(), "ffmpeg.exe"),  # Current directory
        os.path.join(os.getcwd(), "ffmpeg", "bin", "ffmpeg.exe"),  # Local ffmpeg folder
        r"C:\ffmpeg\bin\ffmpeg.exe",  # Common installation path
        r"D:\ffmpeg\bin\ffmpeg.exe",  # Alternative installation path
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",  # Program Files
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",  # Program Files (x86)
    ]
    
    # Try to find FFmpeg in any of these locations
    for path in possible_paths:
        if os.path.exists(path):
            print(f"Found FFmpeg at: {path}")
            return path
    
    print("FFmpeg not found! Please make sure FFmpeg is installed and update the path.")
    print("Download FFmpeg from: https://www.gyan.dev/ffmpeg/builds/")
    print("Extract it and place the 'ffmpeg.exe' file in the same folder as this bot.")
    return None

FFMPEG_PATH = find_ffmpeg()

# DeepSeek API configuration
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# YouTube DL options
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

if FFMPEG_PATH:
    YTDL_OPTIONS['ffmpeg_location'] = FFMPEG_PATH

# FFmpeg options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

if FFMPEG_PATH:
    FFMPEG_OPTIONS['executable'] = FFMPEG_PATH

# Create YT DLP client
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.cog = ctx.cog
        self.queue = []
        self.current = None
        self.voice = None
        self.loop = asyncio.get_event_loop()

    async def connect_to_voice(self, ctx):
        if ctx.author.voice is None:
            await ctx.send("You need to be in a voice channel to play music!")
            return False
        
        if self.voice is None:
            self.voice = await ctx.author.voice.channel.connect()
        elif self.voice.channel != ctx.author.voice.channel:
            await self.voice.move_to(ctx.author.voice.channel)
        
        return True

    def is_spotify_url(self, url):
        parsed = urlparse(url)
        return parsed.hostname in ['open.spotify.com', 'spotify.com']

    def is_youtube_url(self, url):
        parsed = urlparse(url)
        return parsed.hostname in ['www.youtube.com', 'youtube.com', 'youtu.be']

    async def get_track_url(self, query):
        if self.is_spotify_url(query):
            # For Spotify links, we'll search the song name on YouTube
            try:
                track_name = query.split('/')[-1]
                return f"ytsearch:{track_name}"
            except Exception as e:
                print(f"Error processing Spotify URL: {e}")
                return None
        elif self.is_youtube_url(query):
            return query
        else:
            # If it's not a URL, treat it as a search query
            return f"ytsearch:{query}"

    async def play_next(self):
        if self.queue and self.voice:
            self.current = self.queue.pop(0)
            try:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(self.current, download=False))
                
                if 'entries' in data:
                    data = data['entries'][0]

                url = data['url']
                self.voice.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS), 
                              after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), self.loop))
                
                # Enhanced embed with more song information
                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"[{data['title']}]({data['webpage_url']})",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Duration", value=str(datetime.timedelta(seconds=data['duration'])) if 'duration' in data else "Unknown")
                if 'view_count' in data:
                    embed.add_field(name="Views", value=f"{data['view_count']:,}")
                if 'uploader' in data:
                    embed.add_field(name="Channel", value=data['uploader'])
                if 'thumbnail' in data:
                    embed.set_thumbnail(url=data['thumbnail'])
                
                await self.channel.send(embed=embed)
            except Exception as e:
                await self.channel.send(f"An error occurred: {str(e)}")
                await self.play_next()

def load_token():
    try:
        print("Attempting to load .env file...")
        # Attempt to load the .env file
        if not load_dotenv():
            print("Error: .env file not found!")
            return None
        
        print(".env file loaded successfully")
        # Get the tokens from environment variables
        discord_token = os.getenv("DISCORD_TOKEN")
        if not discord_token:
            print("Error: DISCORD_TOKEN not found in .env file!")
            return None

        # Check for DeepSeek API key
        global DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
        if not DEEPSEEK_API_KEY:
            print("Warning: DEEPSEEK_API_KEY not found in .env file! AI features will be disabled.")
        
        print("Tokens loaded successfully")    
        return discord_token
    except UnicodeDecodeError:
        print("Error: .env file has incorrect encoding. Please save it as UTF-8 without BOM.")
        return None
    except Exception as e:
        print(f"Error loading .env file: {str(e)}")
        return None

async def get_ai_response(prompt):
    try:
        if not DEEPSEEK_API_KEY:
            return "AI features are currently disabled. Please add DEEPSEEK_API_KEY to your .env file."
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
        }
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant in a Discord server. Keep responses concise, friendly, and informative."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            return f"Error: {response.status_code} - {response.text}"
            
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@bot.command(name='hello')
async def hello_command(ctx):
    await ctx.send(f'Hello {ctx.author.name}!')

@bot.command(name='ask')
async def ask_command(ctx, *, question):
    """Ask the AI a question using !ask command"""
    async with ctx.typing():
        response = await get_ai_response(question)
        
        # Create an embedded message for the AI response
        embed = discord.Embed(
            title="🤖 AI Response",
            description=response,
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

@bot.command(name='profile')
async def profile_command(ctx):
    user = ctx.author
    created_at = user.created_at.strftime("%Y-%m-%d %H:%M:%S")
    joined_at = ctx.author.joined_at.strftime("%Y-%m-%d %H:%M:%S") if ctx.author.joined_at else "N/A"
    
    # Create an embedded message with user profile data
    embed = discord.Embed(
        title=f"Profile Data for {user.name}",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    # Set the user's avatar as the thumbnail
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    
    # Add fields with user information
    embed.add_field(name="Username", value=user.name, inline=True)
    embed.add_field(name="Discriminator", value=f"#{user.discriminator}", inline=True)
    embed.add_field(name="User ID", value=user.id, inline=True)
    embed.add_field(name="Account Created", value=created_at, inline=True)
    embed.add_field(name="Server Join Date", value=joined_at, inline=True)
    embed.add_field(name="Roles", value=", ".join([role.name for role in user.roles[1:]]) or "No roles", inline=False)
    
    # Add server-specific information
    if ctx.guild:
        embed.add_field(name="Server Nickname", value=user.nick or "No nickname", inline=True)
        embed.add_field(name="Server Boost", value="Yes" if user.premium_since else "No", inline=True)
    
    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    # Prevent the bot from responding to its own messages
    if message.author == bot.user:
        return

    content = message.content.lower()
    
    # Check for "hi" or "hello" in the message
    if content in ['hi', 'hello']:
        await message.channel.send(f'Hello {message.author.name}!')
    elif content == 'give me profile data':
        ctx = await bot.get_context(message)
        await profile_command(ctx)
    elif not content.startswith(('/play', '/stop', '/skip')):  # Don't process AI for music commands
        # Process any message as a question for AI
        async with message.channel.typing():
            response = await get_ai_response(content)
            
            # Create an embedded message for the AI response
            embed = discord.Embed(
                title="🤖 AI Response",
                description=response,
                color=discord.Color.purple(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Asked by {message.author.name}")
            await message.channel.send(embed=embed)

    # Process commands
    await bot.process_commands(message)

@bot.command(name='play')
async def play(ctx, *, query):
    """Play music from YouTube by URL or search term"""
    if not hasattr(bot, 'music_players'):
        bot.music_players = {}

    if ctx.guild.id not in bot.music_players:
        bot.music_players[ctx.guild.id] = MusicPlayer(ctx)

    player = bot.music_players[ctx.guild.id]

    if not await player.connect_to_voice(ctx):
        return

    try:
        # Show searching message for non-URL queries
        if not (player.is_youtube_url(query) or player.is_spotify_url(query)):
            searching_embed = discord.Embed(
                title="🔍 Searching...",
                description=f"Looking for: {query}",
                color=discord.Color.blue()
            )
            await ctx.send(embed=searching_embed)

        track_url = await player.get_track_url(query)
        if track_url:
            player.queue.append(track_url)
            if not player.voice.is_playing():
                await player.play_next()
            else:
                # Get song info for queue message
                data = await asyncio.get_event_loop().run_in_executor(
                    None, 
                    lambda: ytdl.extract_info(track_url, download=False)
                )
                if 'entries' in data:
                    data = data['entries'][0]
                
                embed = discord.Embed(
                    title="🎵 Added to Queue",
                    description=f"[{data['title']}]({data['webpage_url']})",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Duration", value=str(datetime.timedelta(seconds=data['duration'])) if 'duration' in data else "Unknown")
                if 'thumbnail' in data:
                    embed.set_thumbnail(url=data['thumbnail'])
                await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='stop')
async def stop(ctx):
    """Stop the music and clear the queue"""
    if ctx.guild.id in bot.music_players:
        player = bot.music_players[ctx.guild.id]
        if player.voice:
            player.queue = []
            player.voice.stop()
            await player.voice.disconnect()
            await ctx.send("🛑 Stopped playing and cleared the queue!")

@bot.command(name='skip')
async def skip(ctx):
    """Skip the current song"""
    if ctx.guild.id in bot.music_players:
        player = bot.music_players[ctx.guild.id]
        if player.voice and player.voice.is_playing():
            player.voice.stop()
            await ctx.send("⏭️ Skipped the current song!")

@bot.command(name='help')
async def help_command(ctx):
    """Shows all available commands and features"""
    embed = discord.Embed(
        title="🤖 Bot Features & Commands",
        description="Here's everything I can do!",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )

    # Music Commands Section
    embed.add_field(
        name="🎵 Music Commands",
        value="""
• `/play <url>` - Play music from YouTube or Spotify
• `/stop` - Stop playing and clear queue
• `/skip` - Skip to next song
• Just join a voice channel and send the link!
""",
        inline=False
    )

    # Profile Commands Section
    embed.add_field(
        name="👤 Profile Commands",
        value="""
• `/profile` - Show your detailed profile
• Type `give me profile data` - Alternative way to see profile
""",
        inline=False
    )

    # AI Features Section
    embed.add_field(
        name="🧠 AI Features",
        value="""
• Just type any message or question
• I'll respond with AI-powered answers
• Ask me anything about:
  - General knowledge
  - Help with tasks
  - Explanations
  - Creative writing
  - And much more!
""",
        inline=False
    )

    # Chat Commands Section
    embed.add_field(
        name="💬 Chat Commands",
        value="""
• Say `hi` or `hello` - I'll greet you back
• Type any question - I'll answer using AI
""",
        inline=False
    )

    # Examples Section
    embed.add_field(
        name="📝 Examples",
        value="""
• `/play https://www.youtube.com/watch?v=...`
• `/play https://open.spotify.com/track/...`
• "What's the weather like in Paris?"
• "Explain quantum physics"
• "Write a poem about nature"
""",
        inline=False
    )

    # Tips Section
    embed.add_field(
        name="💡 Tips",
        value="""
• For music, join a voice channel first
• AI responses work in any channel
• Use `/help` anytime to see this menu
""",
        inline=False
    )

    embed.set_footer(text=f"Requested by {ctx.author.name}")
    await ctx.send(embed=embed)

def main():
    token = load_token()
    if token:
        try:
            bot.run(token)
        except discord.errors.LoginFailure:
            print("Error: Invalid Discord token!")
        except Exception as e:
            print(f"Error running bot: {str(e)}")
    else:
        print("Bot startup failed due to configuration errors.")

if __name__ == "__main__":
    main() 