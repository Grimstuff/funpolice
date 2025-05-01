import discord
from discord import app_commands
from discord.ext import commands
import re
import json
import os
from discord.ui import Button, View

# Load secrets
with open('secrets.json', 'r') as f:
    secrets = json.load(f)
    BOT_TOKEN = secrets['BOT_TOKEN']

# Function to load config
def load_config():
    with open('config.json', 'r') as f:
        config = json.load(f)
    forbidden = {}
    for replacement, words in config.items():
        if isinstance(words, str):
            forbidden[words.lower()] = replacement
        elif isinstance(words, list):
            for word in words:
                forbidden[word.lower()] = replacement
    return config, forbidden

# Initial config load
config, forbidden = load_config()

# Compile regex pattern
def update_pattern():
    return r'\b(' + '|'.join(re.escape(word) for word in forbidden.keys()) + r')\b'

pattern = update_pattern()

# Set up the bot with intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Function to get or create a webhook
async def get_webhook(channel):
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == "WordFilterWebhook":
                return wh
        return await channel.create_webhook(name="WordFilterWebhook")
    except discord.Forbidden:
        print(f"Cannot create webhook in {channel.name}. Ensure bot has 'Manage Webhooks' permission.")
        return None

# Event handler for new messages
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    original_content = message.content
    match_content = re.sub(r'\s+', '', original_content)  # Remove spaces for terms like "n i g g e r"
    new_content = re.sub(
        pattern,
        lambda m: forbidden[m.group(0).lower()],
        match_content,
        flags=re.IGNORECASE
    )
    
    if new_content != match_content:
        try:
            await message.delete()
        except discord.Forbidden:
            print(f"Cannot delete message in {message.channel.name}. Ensure bot has 'Manage Messages' permission.")
            return
        
        webhook = await get_webhook(message.channel)
        if webhook:
            await webhook.send(
                content=new_content,
                username=message.author.display_name,
                avatar_url=message.author.avatar.url
            )

# Admin-only check for slash commands
def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            raise app_commands.CheckFailure("You need administrator permissions to use this command.")
        return True
    return app_commands.check(predicate)

# Autocomplete function for replacement parameter
async def replacement_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    replacements = list(config.keys())
    filtered = [r for r in replacements if current.lower() in r.lower()]
    return [app_commands.Choice(name=r, value=r) for r in filtered[:25]]

# View class for pagination buttons
class PaginationView(View):
    def __init__(self, user_id: int, pages: list[discord.Embed], current_page: int = 0):
        super().__init__(timeout=300)  # 5-minute timeout
        self.user_id = user_id
        self.pages = pages
        self.current_page = current_page
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        # Previous button
        prev_button = Button(label="Previous", style=discord.ButtonStyle.gray, disabled=self.current_page == 0)
        prev_button.callback = self.previous_page
        self.add_item(prev_button)
        # Next button
        next_button = Button(label="Next", style=discord.ButtonStyle.gray, disabled=self.current_page == len(self.pages) - 1)
        next_button.callback = self.next_page
        self.add_item(next_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the command issuer can use the buttons
        return interaction.user.id == self.user_id

    async def previous_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

# Slash command to add a word to the filter
@app_commands.command(
    name="addfilter",
    description="Add a word to the filter (admin only)."
)
@is_admin()
@app_commands.autocomplete(replacement=replacement_autocomplete)
async def add_filter(
    interaction: discord.Interaction,
    replacement: str,
    word: str
):
    """Add a word to the filter under a replacement phrase."""
    global config, forbidden, pattern
    
    # Normalize inputs
    replacement = replacement.strip()
    word = word.lower().strip()
    
    # Update config
    if replacement in config:
        if isinstance(config[replacement], list):
            if word not in config[replacement]:
                config[replacement].append(word)
            else:
                await interaction.response.send_message(f"Word '{word}' is already in the filter for '{replacement}'.", ephemeral=True)
                return
        else:
            config[replacement] = [config[replacement], word]
    else:
        config[replacement] = [word]
    
    # Save config
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    # Reload forbidden and pattern
    config, forbidden = load_config()
    pattern = update_pattern()
    
    await interaction.response.send_message(f"Added word '{word}' to filter with replacement '{replacement}'.", ephemeral=True)

# Slash command to remove a word from the filter
@app_commands.command(
    name="removefilter",
    description="Remove a word from the filter (admin only)."
)
@is_admin()
async def remove_filter(
    interaction: discord.Interaction,
    word: str
):
    """Remove a word from the filter."""
    global config, forbidden, pattern
    
    word = word.lower().strip()
    found = False
    
    # Search for the word in config
    for replacement, words in list(config.items()):
        if isinstance(words, list) and word in words:
            config[replacement].remove(word)
            if not config[replacement]:  # Remove empty lists
                del config[replacement]
            found = True
        elif isinstance(words, str) and words.lower() == word:
            del config[replacement]
            found = True
    
    if not found:
        await interaction.response.send_message(f"Word '{word}' not found in the filter.", ephemeral=True)
        return
    
    # Save config
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    # Reload forbidden and pattern
    config, forbidden = load_config()
    pattern = update_pattern()
    
    await interaction.response.send_message(f"Removed word '{word}' from the filter.", ephemeral=True)

# Slash command to reload the config
@app_commands.command(
    name="reloadconfig",
    description="Reload the config file (admin only)."
)
@is_admin()
async def reload_config(interaction: discord.Interaction):
    """Reload the config.json file."""
    global config, forbidden, pattern
    
    try:
        config, forbidden = load_config()
        pattern = update_pattern()
        await interaction.response.send_message("Config file reloaded successfully.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to reload config: {str(e)}", ephemeral=True)

# Slash command to list filters
@app_commands.command(
    name="listfilters",
    description="List all word filters (admin only)."
)
@is_admin()
async def list_filters(interaction: discord.Interaction):
    """List all word filters in a paginated embed."""
    if not config:
        await interaction.response.send_message("No filters found in config.", ephemeral=True)
        return
    
    # Create pages (5 categories per page)
    items_per_page = 5
    replacements = list(config.items())
    pages = []
    
    for i in range(0, len(replacements), items_per_page):
        embed = discord.Embed(title="Word Filters", color=0x00ff00)
        embed.set_footer(text=f"Page {i // items_per_page + 1} of {len(replacements) // items_per_page + 1}")
        for replacement, words in replacements[i:i + items_per_page]:
            # Convert words to string if it's a single string
            words_str = ", ".join(words) if isinstance(words, list) else words
            embed.add_field(name=replacement, value=words_str, inline=False)
        pages.append(embed)
    
    # Send the first page with navigation buttons
    view = PaginationView(user_id=interaction.user.id, pages=pages)
    await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

# Sync commands on bot startup
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Error handler for slash command checks
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
    else:
        raise error

# Add commands to the bot's command tree
bot.tree.add_command(add_filter)
bot.tree.add_command(remove_filter)
bot.tree.add_command(reload_config)
bot.tree.add_command(list_filters)

# Run the bot
bot.run(BOT_TOKEN)