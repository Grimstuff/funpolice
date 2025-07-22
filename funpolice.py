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

# Ensure configs directory exists
CONFIGS_DIR = 'configs'
if not os.path.exists(CONFIGS_DIR):
    os.makedirs(CONFIGS_DIR)

# Function to sanitize server name for filename
def sanitize_filename(name):
    """Remove or replace characters that aren't valid in filenames"""
    # Replace invalid characters with underscores
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Remove any remaining problematic characters and limit length
    name = ''.join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
    return name[:50]  # Limit length to avoid filesystem issues

# Function to get server config filename (new naming convention)
def get_config_filename(guild_id, guild_name=None):
    if guild_name:
        sanitized_name = sanitize_filename(guild_name)
        return os.path.join(CONFIGS_DIR, f'{sanitized_name}_{guild_id}.json')
    else:
        # Fallback to just ID if name isn't available
        return os.path.join(CONFIGS_DIR, f'{guild_id}.json')

# Function to find existing config file (handles migration from old naming)
def find_existing_config(guild_id, guild_name=None):
    """Find existing config file, checking old naming conventions and migrating if needed"""
    # Try new naming convention first (server_name_id.json)
    if guild_name:
        new_filename = get_config_filename(guild_id, guild_name)
        if os.path.exists(new_filename):
            return new_filename
    
    # Check for old naming conventions and migrate them
    migration_candidates = []
    
    # Old naming convention 1: config_id_servername.json
    if guild_name:
        old_filename_1 = os.path.join(CONFIGS_DIR, f'config_{guild_id}_{sanitize_filename(guild_name)}.json')
        if os.path.exists(old_filename_1):
            migration_candidates.append(old_filename_1)
    
    # Old naming convention 2: config_id.json
    old_filename_2 = os.path.join(CONFIGS_DIR, f'config_{guild_id}.json')
    if os.path.exists(old_filename_2):
        migration_candidates.append(old_filename_2)
    
    # Very old naming convention: config_id.json in root directory
    root_filename = f'config_{guild_id}.json'
    if os.path.exists(root_filename):
        migration_candidates.append(root_filename)
    
    # If we found old files, migrate the first one found
    if migration_candidates:
        old_file = migration_candidates[0]
        new_filename = get_config_filename(guild_id, guild_name)
        
        try:
            # If the new filename already exists (shouldn't happen but just in case)
            if os.path.exists(new_filename):
                print(f"Warning: {new_filename} already exists, skipping migration of {old_file}")
                return new_filename
            
            os.rename(old_file, new_filename)
            print(f"Migrated config file from {old_file} to {new_filename}")
            
            # Clean up any other old files for this guild to avoid confusion
            for old_file_cleanup in migration_candidates[1:]:
                try:
                    os.remove(old_file_cleanup)
                    print(f"Cleaned up old config file: {old_file_cleanup}")
                except OSError:
                    pass  # File might already be gone
                    
            return new_filename
        except OSError as e:
            print(f"Failed to migrate config file from {old_file} to {new_filename}: {e}")
            return old_file  # Return the old file if migration fails
    
    return None

# Function to load server-specific config
def load_server_config(guild_id, guild_name=None):
    existing_file = find_existing_config(guild_id, guild_name)
    
    # If config doesn't exist, return empty config
    if not existing_file:
        return {}, {}
    
    try:
        with open(existing_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError):
        return {}, {}
    
    # Build forbidden dictionary
    forbidden = {}
    for replacement, words in config.items():
        if isinstance(words, str):
            forbidden[words.lower()] = replacement
        elif isinstance(words, list):
            for word in words:
                forbidden[word.lower()] = replacement
    
    return config, forbidden

# Function to save server-specific config
def save_server_config(guild_id, config, guild_name=None):
    # Get the current filename (which might be an old one that needs updating)
    current_file = find_existing_config(guild_id, guild_name)
    new_filename = get_config_filename(guild_id, guild_name)
    
    # If the current file has a different name than the new standard, rename it
    if current_file and current_file != new_filename:
        try:
            # Only rename if the new filename doesn't already exist
            if not os.path.exists(new_filename):
                os.rename(current_file, new_filename)
                print(f"Updated config filename from {current_file} to {new_filename}")
        except OSError:
            # If rename fails, just use the new filename for saving
            pass
    
    # Save the config using the new naming convention
    with open(new_filename, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# Function to get regex pattern for a server
def get_pattern_for_server(forbidden):
    if not forbidden:
        return None
    return r'\b(' + '|'.join(re.escape(word) + r's?' for word in forbidden.keys()) + r')\b'

# Function to preserve capitalization from original to replacement
def preserve_case(original, replacement):
    """Preserve the capitalization pattern of the original word in the replacement"""
    if not original or not replacement:
        return replacement
    
    # If original is all uppercase
    if original.isupper():
        return replacement.upper()
    
    # If original is all lowercase
    if original.islower():
        return replacement.lower()
    
    # If original is title case (first letter uppercase)
    if original[0].isupper() and (len(original) == 1 or original[1:].islower()):
        return replacement.capitalize()
    
    # For mixed case, try to preserve as much pattern as possible
    result = []
    for i, char in enumerate(replacement):
        if i < len(original):
            if original[i].isupper():
                result.append(char.upper())
            else:
                result.append(char.lower())
        else:
            # For characters beyond original length, use lowercase
            result.append(char.lower())
    
    return ''.join(result)

# Function to handle pluralization of replacements with case preservation
def pluralize_replacement(match, replacement, forbidden):
    # Check if the match ends with 's' and it's not part of the original word
    base_match = match[:-1] if match.endswith('s') or match.endswith('S') else match
    if base_match.lower() in forbidden:
        # Simple English pluralization for the replacement
        plural_replacement = replacement
        if replacement.endswith('y'):
            plural_replacement = replacement[:-1] + 'ies'  # city -> cities
        elif replacement.endswith('sh') or replacement.endswith('ch') or replacement.endswith('x'):
            plural_replacement = replacement + 'es'  # bush -> bushes, church -> churches, box -> boxes
        else:
            plural_replacement = replacement + 's'  # cat -> cats
        
        # Preserve case from the original match
        return preserve_case(match, plural_replacement)
    
    return preserve_case(match, replacement)

# Set up the bot with intents
intents = discord.Intents.default()
intents.message_content = True
# Using a non-standard prefix to avoid conflicts with other bots
# We'll only use slash commands, but need to set a prefix for the Bot class
bot = commands.Bot(command_prefix='__funpolice__', intents=intents, help_command=None)

# Adding an event handler to suppress command not found errors
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Silently ignore command not found errors
        return
    # For other errors, print them to console
    print(f"Command error: {error}")

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
    if message.author.bot or not message.guild:
        return
    
    # Load server-specific config
    config, forbidden = load_server_config(message.guild.id, message.guild.name)
    
    # If no config exists for this server, do nothing
    if not forbidden:
        return
    
    pattern = get_pattern_for_server(forbidden)
    if not pattern:
        return
    
    original_content = message.content
    new_content = original_content
    
    # Handle spaced-out words first (e.g., "f a g" or "F A G")
    nospace_content = re.sub(r'\s+', '', original_content)
    space_matches = re.findall(pattern, nospace_content, flags=re.IGNORECASE)
    
    if space_matches:
        for match in space_matches:
            # Get the base form (without trailing 's' if it exists)
            base_match = match[:-1] if (match.endswith('s') or match.endswith('S')) and match[:-1].lower() in forbidden else match
            replacement = forbidden.get(base_match.lower(), base_match)
            
            # Handle pluralization with case preservation
            if (match.endswith('s') or match.endswith('S')) and match[:-1].lower() in forbidden:
                final_replacement = pluralize_replacement(match, replacement, forbidden)
            else:
                final_replacement = preserve_case(match, replacement)
            
            # Create a pattern to find the spaced version in the original content
            # This creates a pattern like "f\s*a\s*g" for "fag"
            spaced_pattern_chars = []
            for i, char in enumerate(base_match):
                if i > 0:
                    spaced_pattern_chars.append(r'\s*')
                spaced_pattern_chars.append(re.escape(char))
            
            # Handle plural 's' if present
            if (match.endswith('s') or match.endswith('S')) and match[:-1].lower() in forbidden:
                spaced_pattern_chars.append(r'\s*[sS]')
            
            spaced_pattern = ''.join(spaced_pattern_chars)
            
            # Replace in the content with case-insensitive matching
            new_content = re.sub(spaced_pattern, final_replacement, new_content, flags=re.IGNORECASE)
    
    # Now process regular matches with case preservation
    def replace_word(m):
        match = m.group(0)
        # Get the base form (without trailing 's' if it exists)
        base_match = match[:-1] if (match.endswith('s') or match.endswith('S')) and match[:-1].lower() in forbidden else match
        replacement = forbidden.get(base_match.lower(), base_match)
        
        # Handle pluralization with case preservation
        if (match.endswith('s') or match.endswith('S')) and match[:-1].lower() in forbidden:
            return pluralize_replacement(match, replacement, forbidden)
        else:
            return preserve_case(match, replacement)
    
    new_content = re.sub(pattern, replace_word, new_content, flags=re.IGNORECASE)
    
    if new_content != original_content:
        try:
            await message.delete()
        except discord.Forbidden:
            print(f"Cannot delete message in {message.channel.name}. Ensure bot has 'Manage Messages' permission.")
            return
        
        webhook = await get_webhook(message.channel)
        if webhook:
            # Check if the message is a reply
            # Updated code using Discord's native quote formatting instead of embeds
            if message.reference and message.reference.message_id:
                try:
                    # Try to fetch the message being replied to
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                    
                    # Format for replied content - truncate if too long
                    replied_content = replied_msg.content
                    if not replied_content:  # Check if the message has no text content
                        replied_content = "*[message had no text content]*"
                    
                    if len(replied_content) > 100:
                        replied_content = replied_content[:100] + "..."
                    
                    # Create a quoted text format with cleaner mention handling
                    # Format: > @Username: Message content  (if not a bot)
                    # Format: > Username: Message content   (if a bot)
                    if not replied_msg.author.bot:
                        quoted_text = f"> {replied_msg.author.mention}: {replied_content}"
                    else:
                        quoted_text = f"> **{replied_msg.author.display_name}:** {replied_content}"
                    
                    # Combine quote with the filtered message
                    # Single line break without extra space
                    combined_content = f"{quoted_text}\n{new_content}"
                    
                    await webhook.send(
                        content=combined_content,
                        username=message.author.display_name,
                        avatar_url=message.author.avatar.url if message.author.avatar else None,
                        allowed_mentions=discord.AllowedMentions(users=[replied_msg.author])  # Ensure only the replied user gets pinged
                    )
                except discord.NotFound:
                    # If we can't find the replied message, just send the filtered message
                    await webhook.send(
                        content=new_content,
                        username=message.author.display_name,
                        avatar_url=message.author.avatar.url if message.author.avatar else None,
                        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False)  # Default safe mention settings
                    )
            else:
                # Not a reply, just send the filtered message
                await webhook.send(
                    content=new_content,
                    username=message.author.display_name,
                    avatar_url=message.author.avatar.url if message.author.avatar else None,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False)  # Default safe mention settings
                )

# Admin-only check for slash commands
def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            raise app_commands.CheckFailure("You need administrator permissions to use this command.")
        return True
    return app_commands.check(predicate)

# Server-specific autocomplete function for replacement parameter
async def replacement_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
    
    config, _ = load_server_config(interaction.guild.id, interaction.guild.name)
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

# Slash command to add multiple words to the filter
@app_commands.command(
    name="addfilter",
    description="Add one or more words to the filter (admin only)."
)
@is_admin()
@app_commands.autocomplete(replacement=replacement_autocomplete)
async def add_filter(
    interaction: discord.Interaction,
    replacement: str,
    words: str
):
    """Add multiple words to the filter under a replacement phrase.
    Separate words with commas."""
    
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    
    # Load server-specific config
    config, forbidden = load_server_config(interaction.guild.id, interaction.guild.name)
    
    # Normalize inputs
    replacement = replacement.strip()
    # Split by commas and remove whitespace from each word
    word_list = [word.lower().strip() for word in words.split(',') if word.strip()]
    
    if not word_list:
        await interaction.response.send_message("No valid words provided.", ephemeral=True)
        return
    
    # Keep track of added words
    added_words = []
    already_filtered = []
    
    # Update config
    if replacement in config:
        if isinstance(config[replacement], list):
            for word in word_list:
                if word not in config[replacement]:
                    config[replacement].append(word)
                    added_words.append(word)
                else:
                    already_filtered.append(word)
        else:
            # Convert single value to list and add new words
            existing_word = config[replacement]
            config[replacement] = [existing_word]
            for word in word_list:
                if word != existing_word:
                    config[replacement].append(word)
                    added_words.append(word)
                else:
                    already_filtered.append(word)
    else:
        config[replacement] = word_list
        added_words = word_list
    
    # Save server-specific config
    save_server_config(interaction.guild.id, config, interaction.guild.name)
    
    # Prepare response message
    response = []
    if added_words:
        response.append(f"Added {len(added_words)} word(s) to filter with replacement '{replacement}' for {interaction.guild.name}:")
        response.append(", ".join(f"'{word}'" for word in added_words))
    
    if already_filtered:
        words_with_quotes = [f"'{word}'" for word in already_filtered]
        response.append(f"These words were already in the filter: {', '.join(words_with_quotes)}")
    
    await interaction.response.send_message("\n".join(response), ephemeral=True)

# Slash command to remove a word from the filter
@app_commands.command(
    name="deletefilter",
    description="Remove a specific word from the filter (admin only)."
)
@is_admin()
async def delete_filter(
    interaction: discord.Interaction,
    word: str
):
    """Remove a specific word from the filter."""
    
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    
    # Load server-specific config
    config, forbidden = load_server_config(interaction.guild.id, interaction.guild.name)
    
    word = word.lower().strip()
    found = False
    
    # Search for the word in config
    for replacement, words in list(config.items()):
        if isinstance(words, list) and word in words:
            config[replacement].remove(word)
            if not config[replacement]:  # Remove empty lists
                del config[replacement]
            found = True
            break
        elif isinstance(words, str) and words.lower() == word:
            del config[replacement]
            found = True
            break
    
    if not found:
        await interaction.response.send_message(f"Word '{word}' not found in the filter for {interaction.guild.name}.", ephemeral=True)
        return
    
    # Save server-specific config
    save_server_config(interaction.guild.id, config, interaction.guild.name)
    
    await interaction.response.send_message(f"Removed word '{word}' from the filter for {interaction.guild.name}.", ephemeral=True)

# Command to delete an entire replacement category
@app_commands.command(
    name="deletereplacement",
    description="Delete an entire replacement category and all associated words (admin only)."
)
@is_admin()
@app_commands.autocomplete(replacement=replacement_autocomplete)
async def delete_replacement(
    interaction: discord.Interaction,
    replacement: str
):
    """Delete an entire replacement category and all associated words."""
    
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    
    # Load server-specific config
    config, forbidden = load_server_config(interaction.guild.id, interaction.guild.name)
    
    replacement = replacement.strip()
    
    if replacement not in config:
        await interaction.response.send_message(f"Replacement category '{replacement}' not found in {interaction.guild.name}.", ephemeral=True)
        return
    
    # Get the words for confirmation message
    words = config[replacement]
    word_count = 1 if isinstance(words, str) else len(words)
    words_str = words if isinstance(words, str) else ", ".join(words)
    
    # Create a warning message with confirmation button
    warning_message = (
        f"⚠️ **WARNING** ⚠️\n\n"
        f"You are about to delete the replacement category '{replacement}' and ALL {word_count} associated word(s) from {interaction.guild.name}:\n"
        f"```{words_str}```\n"
        f"This action cannot be undone. Please confirm or cancel:"
    )
    
    # Create confirmation view
    view = ConfirmationView(user_id=interaction.user.id, guild_id=interaction.guild.id, guild_name=interaction.guild.name, replacement=replacement)
    await interaction.response.send_message(warning_message, view=view, ephemeral=True)

# Slash command to reload the config
@app_commands.command(
    name="reloadconfig",
    description="Reload the config file for this server (admin only)."
)
@is_admin()
async def reload_config(interaction: discord.Interaction):
    """Reload the server-specific config file."""
    
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    
    try:
        config, forbidden = load_server_config(interaction.guild.id, interaction.guild.name)
        await interaction.response.send_message(f"Config file reloaded successfully for {interaction.guild.name}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to reload config for {interaction.guild.name}: {str(e)}", ephemeral=True)

# Slash command to list filters
@app_commands.command(
    name="listfilters",
    description="List all word filters for this server (admin only)."
)
@is_admin()
async def list_filters(interaction: discord.Interaction):
    """List all word filters in a paginated embed."""
    
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    
    config, forbidden = load_server_config(interaction.guild.id, interaction.guild.name)
    
    if not config:
        await interaction.response.send_message(f"No filters found for {interaction.guild.name}.", ephemeral=True)
        return
    
    # Create pages (5 categories per page)
    items_per_page = 5
    replacements = list(config.items())
    pages = []
    
    for i in range(0, len(replacements), items_per_page):
        embed = discord.Embed(title=f"Word Filters - {interaction.guild.name}", color=0x00ff00)
        embed.set_footer(text=f"Page {i // items_per_page + 1} of {(len(replacements) - 1) // items_per_page + 1}")
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
    print(f"Bot is ready to serve {len(bot.guilds)} guild(s)")
    print(f"Config files will be stored in: {os.path.abspath(CONFIGS_DIR)}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Create a confirmation button view for deletion
class ConfirmationView(View):
    def __init__(self, user_id: int, guild_id: int, guild_name: str, replacement: str):
        super().__init__(timeout=60)  # 60-second timeout
        self.user_id = user_id
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.replacement = replacement
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the command issuer can use the buttons
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Confirm Deletion", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Load server config
        config, forbidden = load_server_config(self.guild_id, self.guild_name)
        
        # Get word count for confirmation message
        words = config.get(self.replacement, [])
        word_count = 1 if isinstance(words, str) else len(words)
        
        # Delete the category
        if self.replacement in config:
            del config[self.replacement]
            save_server_config(self.guild_id, config, self.guild_name)
        
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(
            content=f"Successfully deleted replacement category '{self.replacement}' with {word_count} word(s).",
            view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Deletion canceled.", view=None)

# Error handler for slash command checks
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
    else:
        # Log the error instead of raising it
        print(f"Error in slash command: {error}")
        await interaction.response.send_message("An error occurred while executing the command.", ephemeral=True)

# Add commands to the bot's command tree
bot.tree.add_command(add_filter)
bot.tree.add_command(delete_filter)
bot.tree.add_command(delete_replacement)
bot.tree.add_command(reload_config)
bot.tree.add_command(list_filters)

# Run the bot
bot.run(BOT_TOKEN)