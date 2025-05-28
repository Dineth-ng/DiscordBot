import discord
from discord.ext import commands
import google.generativeai as genai
import os
from dotenv import load_dotenv
import yt_dlp
import asyncio
from discord import app_commands
from collections import deque

# Load environment variables
load_dotenv()

# Configure Discord
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    raise ValueError("Please set DISCORD_TOKEN in .env file")

# Configure Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("Please set GEMINI_API_KEY in .env file")

GUILD_ID = 1376716524840157345

# Create the structure for queueing songs
SONG_QUEUES = {}

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

async def search_ytdlp_async(query, ydl_opts):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_opts))

def _extract(query, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')
safety_settings = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "BLOCK_NONE"
    },
]

chat = model.start_chat(history=[])

async def play_next_song(voice_client, guild_id, channel):
    if SONG_QUEUES[guild_id]:
        audio_url, title = SONG_QUEUES[guild_id].popleft()

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }

        try:
            # Create FFmpeg audio source directly without probing
            source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_options)
            transformed_source = discord.PCMVolumeTransformer(source, volume=0.5)
            
            def after_play(error):
                if error:
                    print(f"Error playing {title}: {error}")
                    asyncio.run_coroutine_threadsafe(channel.send(f"❌ Error playing {title}: {error}"), bot.loop)
                asyncio.run_coroutine_threadsafe(play_next_song(voice_client, guild_id, channel), bot.loop)

            voice_client.play(transformed_source, after=after_play)
            await channel.send(f"🎶 Now playing: **{title}**")
        except Exception as e:
            print(f"Error playing {title}: {e}")
            await channel.send(f"Error playing the song: {str(e)}")
            await play_next_song(voice_client, guild_id, channel)
    else:
        await voice_client.disconnect()
        SONG_QUEUES[guild_id] = deque()

@bot.hybrid_command(name="skip", description="Skips the current playing song")
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skipped the current song.")
    else:
        await ctx.send("❌ Not playing anything to skip.")

@bot.hybrid_command(name="pause", description="Pause the currently playing song")
async def pause(ctx):
    voice_client = ctx.voice_client

    if voice_client is None:
        return await ctx.send("❌ I'm not in a voice channel.")

    if not voice_client.is_playing():
        return await ctx.send("❌ Nothing is currently playing.")
    
    voice_client.pause()
    await ctx.send("⏸️ Playback paused!")

@bot.hybrid_command(name="resume", description="Resume the currently paused song")
async def resume(ctx):
    voice_client = ctx.voice_client

    if voice_client is None:
        return await ctx.send("❌ I'm not in a voice channel.")

    if not voice_client.is_paused():
        return await ctx.send("❌ I'm not paused right now.")
    
    voice_client.resume()
    await ctx.send("▶️ Playback resumed!")

@bot.hybrid_command(name="stop", description="Stop playback and clear the queue")
async def stop(ctx):
    voice_client = ctx.voice_client

    if not voice_client or not voice_client.is_connected():
        return await ctx.send("❌ I'm not connected to any voice channel.")

    guild_id_str = str(ctx.guild.id)
    if guild_id_str in SONG_QUEUES:
        SONG_QUEUES[guild_id_str].clear()

    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()

    await voice_client.disconnect()
    await ctx.send("⏹️ Stopped playback and disconnected!")

@bot.hybrid_command(name="play", description="Play a song or add it to the queue")
async def play(ctx, *, song_query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ You must be in a voice channel!")

    voice_channel = ctx.author.voice.channel
    voice_client = ctx.voice_client

    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_channel != voice_client.channel:
        await voice_client.move_to(voice_channel)

    ydl_options = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
        'extract_flat': 'in_playlist'
    }

    try:
        await ctx.defer()
        
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            try:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(f"ytsearch:{song_query}", download=False))
                
                if not info or 'entries' not in info or not info['entries']:
                    return await ctx.send("❌ No results found.")
                
                first_track = info['entries'][0]
                # Get the direct audio URL
                format_info = await asyncio.get_event_loop().run_in_executor(
                    None, 
                    lambda: ydl.extract_info(first_track['url'], download=False)
                )
                
                audio_url = format_info['url']
                title = format_info.get('title', 'Untitled')
                
                guild_id = str(ctx.guild.id)
                if guild_id not in SONG_QUEUES:
                    SONG_QUEUES[guild_id] = deque()

                SONG_QUEUES[guild_id].append((audio_url, title))

                if voice_client.is_playing() or voice_client.is_paused():
                    await ctx.send(f"📝 Added to queue: **{title}**")
                else:
                    await ctx.send(f"🎵 Now playing: **{title}**")
                    await play_next_song(voice_client, guild_id, ctx.channel)

            except Exception as e:
                await ctx.send(f"❌ Error: Could not process the song.")
                print(f"Error extracting info: {e}")

    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")
        print(f"Error in play command: {e}")

@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.event
async def on_message(message):
    # Prevent bot from replying to itself
    if message.author == bot.user:
        return

    if message.content.startswith("!ask "):
        user_input = message.content[5:]  # Remove "!ask " prefix
        
        # If the message is a reply, include the replied message content in the context
        if message.reference and message.reference.resolved:
            replied_msg = message.reference.resolved
            user_input = f"Previous message: '{replied_msg.content}'\nNew question: {user_input}"
        
        async with message.channel.typing():
            try:
                response = model.generate_content(user_input)
                response_text = response.text
                
                # Split long messages if they exceed Discord's character limit
                if len(response_text) > 2000:
                    chunks = [response_text[i:i+2000] for i in range(0, len(response_text), 2000)]
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response_text)
            except Exception as e:
                error_message = f"Error: {str(e)}\nPlease try again in a moment."
                await message.reply(error_message)
                print(f"Error details: {str(e)}")

    # This line is important to process commands
    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)
