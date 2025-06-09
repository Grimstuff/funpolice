import discord # type: ignore
from discord import app_commands # type: ignore
from discord.ext import commands # type: ignore
import re
import json
import os
import unicodedata
from discord.ui import Button, View # type: ignore

# Load secrets
with open('secrets.json', 'r') as f:
    secrets = json.load(f)
    BOT_TOKEN = secrets['BOT_TOKEN']

def normalize_text_for_filtering(text):
    """
    Normalize text to catch various evasion attempts including:
    - Discord markdown formatting (*italic*, **bold**, etc.)
    - Unicode styling characters (mathematical bold/italic alphabets)
    - Zero-width characters
    - Mixed case with spaces
    """
    # Step 1: Remove Discord markdown formatting
    # Remove bold (**text**)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    # Remove italic (*text*)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    # Remove strikethrough (~~text~~)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    # Remove underline (__text__)
    text = re.sub(r'__(.*?)__', r'\1', text)
    # Remove spoiler (||text||)
    text = re.sub(r'\|\|(.*?)\|\|', r'\1', text)
    # Remove code blocks and inline code
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`(.*?)`', r'\1', text)
    
    # Step 2: Unicode normalization to handle styled characters
    # First normalize to decomposed form
    text = unicodedata.normalize('NFD', text)
    
    # Step 3: Remove zero-width characters and other invisible characters
    zero_width_chars = [
        '\u200b',  # Zero Width Space
        '\u200c',  # Zero Width Non-Joiner
        '\u200d',  # Zero Width Joiner
        '\u2060',  # Word Joiner
        '\ufeff',  # Zero Width No-Break Space
    ]
    for char in zero_width_chars:
        text = text.replace(char, '')
    
    # Step 4: Convert Unicode mathematical/styled alphabets to regular ASCII
    styled_mappings = {}
    
    # Mathematical Bold (U+1D400-U+1D433 for A-Z, U+1D41A-U+1D44D for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D400 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D41A + i)] = char
    
    # Mathematical Italic (U+1D434-U+1D467 for A-Z, U+1D44E-U+1D481 for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D434 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D44E + i)] = char
    
    # Mathematical Bold Italic (U+1D468-U+1D49B for A-Z, U+1D482-U+1D4B5 for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D468 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D482 + i)] = char
    
    # Mathematical Script (U+1D49C-U+1D4CF for A-Z, U+1D4B6-U+1D4E9 for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D49C + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D4B6 + i)] = char
    
    # Mathematical Double-Struck (U+1D538-U+1D56B for A-Z, U+1D552-U+1D585 for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D538 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D552 + i)] = char
    
    # Mathematical Sans-Serif (U+1D5A0-U+1D5D3 for A-Z, U+1D5BA-U+1D5ED for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D5A0 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D5BA + i)] = char
    
    # Mathematical Sans-Serif Bold (U+1D5D4-U+1D607 for A-Z, U+1D5EE-U+1D621 for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D5D4 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D5EE + i)] = char
    
    # Mathematical Sans-Serif Italic (U+1D608-U+1D63B for A-Z, U+1D622-U+1D655 for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D608 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D622 + i)] = char
    
    # Mathematical Monospace (U+1D670-U+1D6A3 for A-Z, U+1D68A-U+1D6BD for a-z)
    for i, char in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        styled_mappings[chr(0x1D670 + i)] = char
    for i, char in enumerate('abcdefghijklmnopqrstuvwxyz'):
        styled_mappings[chr(0x1D68A + i)] = char
    
    # Apply the mappings
    for styled_char, normal_char in styled_mappings.items():
        text = text.replace(styled_char, normal_char)
    
    # Step 5: Additional character substitutions for common leetspeak
    char_substitutions = {
        '0': 'o', '3': 'e', '1': 'i', '4': 'a', '5': 's', '7': 't',
        '@': 'a', '!': 'i', '$': 's', '+': 't', '8': 'b'
    }
    
    # Apply character substitutions
    for old_char, new_char in char_substitutions.items():
        text = text.replace(old_char, new_char)
    
    return text

def create_flexible_pattern(word):
    """
    Create a regex pattern that can match a word even with formatting characters
    """
    # Create a pattern that allows for markdown formatting and spaces between characters
    flexible_chars = []
    for char in word.lower():
        if char.isalpha():
            # Allow for various formatting around each letter and case variations
            flexible_chars.append(f'[{char.upper()}{char.lower()}]')
        else:
            flexible_chars.append(re.escape(char))
    
    # Allow for spaces, formatting, and zero-width characters between letters
    pattern_with_spaces = r'(?:\s*\*{0,2}\s*|\s*_{0,2}\s*|\s*~{0,2}\s*|\s*\|{0,2}\s*|\s*`*\s*|\s*[\u200b\u200c\u200d\u2060\ufeff]*\s*)'.join(flexible_chars)
    
    return r'\b' + pattern_with_spaces + r'(?:s)?\b'

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

# Compile regex pattern - includes optional 's' at the end for plurals
def update_pattern():
    pattern_parts = []
    for word in forbidden.keys():
        pattern_parts.append(re.escape(word))  # Original word
        pattern_parts.append(re.escape(word) + r's')  # Plural form
    
    return r'\b(' + '|'.join(pattern_parts) + r')\b'

pattern = update_pattern()

# Function to handle pluralization of replacements
def pluralize_replacement(match, replacement):
    if replacement.endswith('y'):
        return replacement[:-1] + 'ies'
    elif replacement.endswith('sh') or replacement.endswith('ch') or replacement.endswith('x'):
        return replacement + 'es'
    else:
        return replacement + 's'

# Enhanced message filtering function
def enhanced_message_filter(original_content, forbidden, pattern):
    """
    Enhanced message filtering that handles various evasion techniques
    """
    # Normalize the content to catch evasion attempts
    normalized_content = normalize_text_for_filtering(original_content)
    nospace_content = re.sub(r'\s+', '', normalized_content)
    
    # Test both normalized and no-space versions
    content_versions = [normalized_content, nospace_content]
    
    new_content = original_content
    replacements_made = {}
    
    # Check each version for matches
    for test_content in content_versions:
        # Find matches using the standard pattern first
        matches = re.findall(pattern, test_content, flags=re.IGNORECASE)
        
        if matches:
            for match in matches:
                # Determine the base word and replacement
                is_plural = match.lower().endswith('s')
                base_match = match[:-1] if is_plural and match[:-1].lower() in forbidden else match
                
                # Get the replacement
                if base_match.lower() in forbidden:
                    replacement = forbidden[base_match.lower()]
                elif match.lower() in forbidden:
                    replacement = forbidden[match.lower()]
                else:
                    continue
                
                # Handle pluralization
                if is_plural and base_match.lower() in forbidden:
                    replacement = pluralize_replacement(match, replacement)
                
                # Store this replacement to apply to original content
                replacements_made[base_match.lower()] = replacement
    
    # Now apply replacements to original content using flexible patterns
    for word, replacement in replacements_made.items():
        flexible_pattern = create_flexible_pattern(word)
        
        def replace_flexible_match(m):
            original_match = m.group(0)
            # Preserve case of the original
            if original_match.isupper():
                return replacement.upper()
            elif original_match[0].isupper():
                return replacement[0].upper() + replacement[1:].lower()
            return replacement.lower()
        
        new_content = re.sub(flexible_pattern, replace_flexible_match, new_content, flags=re.IGNORECASE)
    
    # Fallback: also check with the original simple pattern matching
    def replace_word(m):
        match = m.group(0)
        base_match = match[:-1] if match.endswith('s') and match[:-1].lower() in forbidden else match
        replacement = forbidden.get(base_match.lower(), base_match)
        
        if match.endswith('s') and match[:-1].lower() in forbidden:
            replacement = pluralize_replacement(match, replacement)
            
        # Preserve capitalization
        if match.isupper():
            return replacement.upper()
        elif match[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement
    
    new_content = re.sub(pattern, replace_word, new_content, flags=re.IGNORECASE)
    
    return new_content

# Set up the bot with intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='__funpolice__', intents=intents, help_command=None)

# Adding an event handler to suppress command not found errors
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
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

# Function to get the appropriate avatar URL (guild-specific if available)
def get_avatar_url(user, guild):
    """
    Get the guild-specific avatar URL for a user if available, otherwise fall back to global avatar.
    """
    if user is None or guild is None:
        return None
    
    if hasattr(user, 'guild') and user.guild.id == guild.id and user.guild_avatar:
        return user.guild_avatar.url
    
    try:
        member = guild.get_member(user.id)
        if member and member.guild_avatar:
            return member.guild_avatar.url
    except:
        pass
    
    if hasattr(user, 'avatar') and user.avatar:
        return user.avatar.url
    
    return user.default_avatar.url if hasattr(user, 'default_avatar') else None

# Enhanced event handler for new messages
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    original_content = message.content
    
    # Use the enhanced filtering
    new_content = enhanced_message_filter(original_content, forbidden, pattern)
    
    if new_content != original_content:
        try:
            await message.delete()
        except discord.Forbidden:
            print(f"Cannot delete message in {message.channel.name}. Ensure bot has 'Manage Messages' permission.")
            return
        except discord.NotFound:
            print(f"Message {message.id} already deleted. Continuing with filter process.")
        
        webhook = await get_webhook(message.channel)
        if webhook:
            avatar_url = get_avatar_url(message.author, message.guild)
            
            if avatar_url is None:
                avatar_url = message.author.default_avatar.url if hasattr(message.author, 'default_avatar') else None
            
            # Check if the message is a reply
            if message.reference and message.reference.message_id:
                try:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                    
                    replied_content = replied_msg.content
                    if not replied_content:
                        replied_content = "*[message had no text content]*"
                    
                    if len(replied_content) > 100:
                        replied_content = replied_content[:100] + "..."
                    
                    quoted_text = f"> {replied_msg.author.mention}: {replied_content}"
                    combined_content = f"{quoted_text}\n{new_content}"
                    
                    await webhook.send(
                        content=combined_content,
                        username=message.author.display_name,
                        avatar_url=avatar_url,
                        allowed_mentions=discord.AllowedMentions(
                            users=[replied_msg.author],
                            everyone=False,
                            roles=False
                        )
                    )
                except discord.NotFound:
                    await webhook.send(
                        content=new_content,
                        username=message.author.display_name,
                        avatar_url=avatar_url,
                        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False)
                    )
            else:
                await webhook.send(
                    content=new_content,
                    username=message.author.display_name,
                    avatar_url=avatar_url,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False)
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
        super().__init__(timeout=300)
        self.user_id = user_id
        self.pages = pages
        self.current_page = current_page
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        prev_button = Button(label="Previous", style=discord.ButtonStyle.gray, disabled=self.current_page == 0)
        prev_button.callback = self.previous_page
        self.add_item(prev_button)
        next_button = Button(label="Next", style=discord.ButtonStyle.gray, disabled=self.current_page == len(self.pages) - 1)
        next_button.callback = self.next_page
        self.add_item(next_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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
    """Add multiple words to the filter under a replacement phrase."""
    global config, forbidden, pattern
    
    replacement = replacement.strip()
    word_list = [word.lower().strip() for word in words.split(',') if word.strip()]
    
    if not word_list:
        await interaction.response.send_message("No valid words provided.", ephemeral=True)
        return
    
    added_words = []
    already_filtered = []
    
    if replacement in config:
        if isinstance(config[replacement], list):
            for word in word_list:
                if word not in config[replacement]:
                    config[replacement].append(word)
                    added_words.append(word)
                else:
                    already_filtered.append(word)
        else:
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
    
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    config, forbidden = load_config()
    pattern = update_pattern()
    
    response = []
    if added_words:
        response.append(f"Added {len(added_words)} word(s) to filter with replacement '{replacement}':")
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
    global config, forbidden, pattern
    
    word = word.lower().strip()
    found = False
    
    for replacement, words in list(config.items()):
        if isinstance(words, list) and word in words:
            config[replacement].remove(word)
            if not config[replacement]:
                del config[replacement]
            found = True
            break
        elif isinstance(words, str) and words.lower() == word:
            del config[replacement]
            found = True
            break
    
    if not found:
        await interaction.response.send_message(f"Word '{word}' not found in the filter.", ephemeral=True)
        return
    
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    config, forbidden = load_config()
    pattern = update_pattern()
    
    await interaction.response.send_message(f"Removed word '{word}' from the filter.", ephemeral=True)

# Create a confirmation button view for deletion
class ConfirmationView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Confirm Deletion", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(content="Deletion confirmed!", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Deletion canceled.", view=None)

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
    global config, forbidden, pattern
    
    replacement = replacement.strip()
    
    if replacement not in config:
        await interaction.response.send_message(f"Replacement category '{replacement}' not found.", ephemeral=True)
        return
    
    words = config[replacement]
    word_count = 1 if isinstance(words, str) else len(words)
    words_str = words if isinstance(words, str) else ", ".join(words)
    
    warning_message = (
        f"⚠️ **WARNING** ⚠️\n\n"
        f"You are about to delete the replacement category '{replacement}' and ALL {word_count} associated word(s):\n"
        f"```{words_str}```\n"
        f"This action cannot be undone. Please confirm or cancel:"
    )
    
    view = ConfirmationView(user_id=interaction.user.id)
    await interaction.response.send_message(warning_message, view=view, ephemeral=True)
    
    await view.wait()
    
    if not view.confirmed:
        return
    
    del config[replacement]
    
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    config, forbidden = load_config()
    pattern = update_pattern()
    
    await interaction.followup.send(
        f"Successfully deleted replacement category '{replacement}' with {word_count} word(s).", 
        ephemeral=True
    )

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
    
    items_per_page = 5
    replacements = list(config.items())
    pages = []
    
    for i in range(0, len(replacements), items_per_page):
        embed = discord.Embed(title="Word Filters", color=0x00ff00)
        embed.set_footer(text=f"Page {i // items_per_page + 1} of {len(replacements) // items_per_page + 1}")
        for replacement, words in replacements[i:i + items_per_page]:
            words_str = ", ".join(words) if isinstance(words, list) else words
            embed.add_field(name=replacement, value=words_str, inline=False)
        pages.append(embed)
    
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