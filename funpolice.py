import discord
from discord.ext import commands
import re
import json

# Load the configuration file
with open('config.json', 'r') as f:
    config = json.load(f)

# Build the forbidden words dictionary
forbidden = {}
for replacement, words in config.items():
    # Handle both single strings and lists for flexibility
    if isinstance(words, str):
        forbidden[words.lower()] = replacement
    elif isinstance(words, list):
        for word in words:
            forbidden[word.lower()] = replacement

# Compile a regex pattern to match whole forbidden words
pattern = r'\b(' + '|'.join(re.escape(word) for word in forbidden.keys()) + r')\b'

# Set up the bot with intents
intents = discord.Intents.default()
intents.message_content = True  # Enable intent to read message content
bot = commands.Bot(command_prefix='!', intents=intents)

# Function to get or create a webhook in the channel
async def get_webhook(channel):
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == "WordFilterWebhook":
                return wh
        # Create a new webhook if none exists
        return await channel.create_webhook(name="WordFilterWebhook")
    except discord.Forbidden:
        print(f"Cannot create webhook in {channel.name}. Ensure the bot has 'Manage Webhooks' permission.")
        return None

# Event handler for new messages
@bot.event
async def on_message(message):
    # Ignore messages from bots (including ourselves)
    if message.author.bot:
        return
    
    original_content = message.content
    # Replace forbidden words case-insensitively
    new_content = re.sub(
        pattern,
        lambda m: forbidden[m.group(0).lower()],
        original_content,
        flags=re.IGNORECASE
    )
    
    # If the message was modified (contained forbidden words)
    if new_content != original_content:
        # Delete the original message
        try:
            await message.delete()
        except discord.Forbidden:
            print(f"Cannot delete message in {message.channel.name}. Ensure the bot has 'Manage Messages' permission.")
            return
        
        # Get or create a webhook and send the modified message
        webhook = await get_webhook(message.channel)
        if webhook:
            await webhook.send(
                content=new_content,
                username=message.author.display_name,  # Use the user's server nickname or username
                avatar_url=message.author.avatar.url   # Use the user's profile photo
            )
    else:
        # Process commands if no forbidden words were found
        await bot.process_commands(message)

# Load the bot token from secrets.json
with open('secrets.json', 'r') as f:
    secrets = json.load(f)
    BOT_TOKEN = secrets['BOT_TOKEN']

# Run the bot
bot.run(BOT_TOKEN)