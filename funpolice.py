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

# Leetspeak character mappings for normalization
LEETSPEAK_MAP = {
    '4': 'a', '@': 'a', '3': 'e', '1': 'i', '!': 'i', '0': 'o', '5': 's', '$': 's', '7': 't', '+': 't',
    '2': 'z', '6': 'g', '8': 'b', '9': 'g'
}

# Function to sanitize server name for filename
def sanitize_filename(name):
    """Remove or replace characters that aren't valid in filenames"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    name = ''.join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
    return name[:50]

# Function to get server config filename
def get_config_filename(guild_id, guild_name=None):
    if guild_name:
        sanitized_name = sanitize_filename(guild_name)
        return os.path.join(CONFIGS_DIR, f'{sanitized_name}_{guild_id}.json')
    else:
        return os.path.join(CONFIGS_DIR, f'{guild_id}.json')

# Function to find existing config file (handles migration from old naming)
def find_existing_config(guild_id, guild_name=None):
    """Find existing config file, checking old naming conventions and migrating if needed"""
    # Try new naming convention first
    if guild_name:
        new_filename = get_config_filename(guild_id, guild_name)
        if os.path.exists(new_filename):
            return new_filename
    
    # Check for old naming conventions and migrate them
    migration_candidates = []
    
    if guild_name:
        old_filename_1 = os.path.join(CONFIGS_DIR, f'config_{guild_id}_{sanitize_filename(guild_name)}.json')
        if os.path.exists(old_filename_1):
            migration_candidates.append(old_filename_1)
    
    old_filename_2 = os.path.join(CONFIGS_DIR, f'config_{guild_id}.json')
    if os.path.exists(old_filename_2):
        migration_candidates.append(old_filename_2)
    
    root_filename = f'config_{guild_id}.json'
    if os.path.exists(root_filename):
        migration_candidates.append(root_filename)
    
    # Migrate the first old file found
    if migration_candidates:
        old_file = migration_candidates[0]
        new_filename = get_config_filename(guild_id, guild_name)
        
        try:
            if os.path.exists(new_filename):
                print(f"Warning: {new_filename} already exists, skipping migration of {old_file}")
                return new_filename
            
            os.rename(old_file, new_filename)
            print(f"Migrated config file from {old_file} to {new_filename}")
            
            # Clean up other old files
            for old_file_cleanup in migration_candidates[1:]:
                try:
                    os.remove(old_file_cleanup)
                    print(f"Cleaned up old config file: {old_file_cleanup}")
                except OSError:
                    pass
                    
            return new_filename
        except OSError as e:
            print(f"Failed to migrate config file from {old_file} to {new_filename}: {e}")
            return old_file
    
    return None

# Function to load server-specific config
def load_server_config(guild_id, guild_name=None):
    existing_file = find_existing_config(guild_id, guild_name)
    
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
    current_file = find_existing_config(guild_id, guild_name)
    new_filename = get_config_filename(guild_id, guild_name)
    
    if current_file and current_file != new_filename:
        try:
            if not os.path.exists(new_filename):
                os.rename(current_file, new_filename)
                print(f"Updated config filename from {current_file} to {new_filename}")
        except OSError:
            pass
    
    with open(new_filename, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# Function to normalize text for evasion detection
def normalize_text(text):
    """Normalize text by removing special characters and converting leetspeak"""
    # Convert to lowercase
    normalized = text.lower()
    
    # Replace leetspeak characters
    for leet, normal in LEETSPEAK_MAP.items():
        normalized = normalized.replace(leet, normal)
    
    # Remove common evasion characters but keep letters and numbers
    # This removes spaces, dots, asterisks, dashes, underscores, etc.
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    
    return normalized

# Function to preserve capitalization from original to replacement
def preserve_case(original, replacement):
    """Preserve the capitalization pattern of the original word in the replacement"""
    if not original or not replacement:
        return replacement
    
    if original.isupper():
        return replacement.upper()
    
    if original.islower():
        return replacement.lower()
    
    if original[0].isupper() and (len(original) == 1 or original[1:].islower()):
        return replacement.capitalize()
    
    # For mixed case, preserve pattern as much as possible
    result = []
    for i, char in enumerate(replacement):
        if i < len(original):
            if original[i].isupper():
                result.append(char.upper())
            else:
                result.append(char.lower())
        else:
            result.append(char.lower())
    
    return ''.join(result)

# Function to handle pluralization
def pluralize_replacement(match, replacement):
    """Handle pluralization for replacements"""
    plural_replacement = replacement
    if replacement.endswith('y'):
        plural_replacement = replacement[:-1] + 'ies'
    elif replacement.endswith(('sh', 'ch', 'x')):
        plural_replacement = replacement + 'es'
    else:
        plural_replacement = replacement + 's'
    
    return preserve_case(match, plural_replacement)

# Function to detect filtered words with evasion techniques
def detect_and_replace_words(content, forbidden):
    """Detect and replace filtered words, handling various evasion techniques"""
    if not forbidden:
        return content

    original_content = content
    new_content = content
    
    # Create a list to track all matches and their positions
    matches_to_replace = []
    
    # For each forbidden word, search for it in various forms
    for forbidden_word, replacement in forbidden.items():
        patterns = []
        
        # 1. Exact word boundaries (normal case)
        patterns.append((rf'\b{re.escape(forbidden_word)}s?\b', forbidden_word, False))
        
        # 2. Simple wildcard replacement patterns
        # This handles cases like f*g, n*gger, etc.
        if len(forbidden_word) >= 3:
            # Create patterns where one or more characters can be replaced by wildcards
            wildcard_chars = r'[*.\-_#!?+=]'
            
            # Single wildcard replacement for each position (except first and last)
            for i in range(1, len(forbidden_word) - 1):
                pattern_parts = []
                for j, char in enumerate(forbidden_word):
                    if j == i:
                        # This position can be original char OR wildcard
                        pattern_parts.append(f'[{char.upper()}{char.lower()}*.\-_#!?+=]')
                    else:
                        pattern_parts.append(f'[{char.upper()}{char.lower()}]')
                
                pattern = r'\b' + ''.join(pattern_parts) + r's?\b'
                patterns.append((pattern, forbidden_word, True))
            
            # Multiple consecutive wildcards in middle positions
            if len(forbidden_word) >= 4:
                pattern_parts = []
                for j, char in enumerate(forbidden_word):
                    if 1 <= j <= len(forbidden_word) - 2:  # Middle positions
                        pattern_parts.append(f'[{char.upper()}{char.lower()}*.\-_#!?+=]')
                    else:  # First and last must be correct letters
                        pattern_parts.append(f'[{char.upper()}{char.lower()}]')
                
                pattern = r'\b' + ''.join(pattern_parts) + r's?\b'
                patterns.append((pattern, forbidden_word, True))
        
        # 3. Spaced out version (e.g., "f a g")
        if len(forbidden_word) >= 3:
            spaced_parts = []
            for i, char in enumerate(forbidden_word):
                if i > 0:
                    spaced_parts.append(r'\s*[^\w\s]*\s*')
                spaced_parts.append(f'[{char.upper()}{char.lower()}]')
            
            spaced_pattern = r'\b' + ''.join(spaced_parts) + r'(?:\s*[^\w\s]*\s*[sS])?' + r'\b'
            patterns.append((spaced_pattern, forbidden_word, True))
        
        # 4. Leetspeak patterns
        if len(forbidden_word) >= 3:
            leet_parts = []
            for char in forbidden_word:
                char_options = [char.upper(), char.lower()]
                # Add leetspeak alternatives
                for leet, normal in LEETSPEAK_MAP.items():
                    if normal == char.lower():
                        char_options.append(re.escape(leet))
                
                leet_parts.append(f'[{"".join(char_options)}]')
            
            leet_pattern = r'\b' + ''.join(leet_parts) + r's?\b'
            patterns.append((leet_pattern, forbidden_word, True))
        
        # 5. Combined leetspeak + wildcard patterns
        if len(forbidden_word) >= 3:
            # Create patterns where each position can be: original letter, leetspeak, OR wildcard
            for i in range(1, len(forbidden_word) - 1):  # Only middle positions can be wildcards
                combined_parts = []
                for j, char in enumerate(forbidden_word):
                    char_options = [char.upper(), char.lower()]
                    
                    # Add leetspeak alternatives for all positions
                    for leet, normal in LEETSPEAK_MAP.items():
                        if normal == char.lower():
                            char_options.append(re.escape(leet))
                    
                    # Add wildcard options for middle positions
                    if j == i:
                        char_options.extend(['*', '.', '-', '_', '#', '!', '?', '+', '='])
                    
                    combined_parts.append(f'[{"".join(re.escape(opt) for opt in char_options)}]')
                
                combined_pattern = r'\b' + ''.join(combined_parts) + r's?\b'
                patterns.append((combined_pattern, forbidden_word, True))
        
        # Find all matches for this word
        for pattern, base_word, is_evasion in patterns:
            try:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    matched_text = match.group(0)
                    
                    # Simple validation for evasion attempts
                    if is_evasion:
                        # Remove word boundaries and check if it's reasonable
                        clean_match = re.sub(r'[^\w]', '', matched_text.lower())
                        clean_target = base_word.lower()
                        
                        # Must have at least 50% of the original letters
                        matching_chars = sum(1 for c in clean_match if c in clean_target)
                        if len(clean_match) > 0 and matching_chars / len(clean_target) < 0.5:
                            continue
                        
                        # Shouldn't be too much longer than original
                        if len(clean_match) > len(clean_target) + 2:
                            continue
                    
                    # Determine if it's plural (simple check)
                    is_plural = matched_text.lower().endswith('s') and len(matched_text) > len(base_word)
                    
                    if is_plural:
                        final_replacement = pluralize_replacement(matched_text, replacement)
                    else:
                        final_replacement = preserve_case(matched_text, replacement)
                    
                    matches_to_replace.append((match.start(), match.end(), final_replacement))
                    
            except re.error as e:
                print(f"Regex error with pattern '{pattern}': {e}")
                continue
    
    # Sort matches by position (reverse order to maintain positions during replacement)
    matches_to_replace.sort(key=lambda x: x[0], reverse=True)
    
    # Remove overlapping matches (keep the first match found)
    filtered_matches = []
    for start, end, repl in matches_to_replace:
        overlaps = False
        for existing_start, existing_end, _ in filtered_matches:
            if not (end <= existing_start or start >= existing_end):
                overlaps = True
                break
        
        if not overlaps:
            filtered_matches.append((start, end, repl))
    
    # Apply replacements
    for start, end, replacement in filtered_matches:
        new_content = new_content[:start] + replacement + new_content[end:]
    
    return new_content

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

# Set up the bot with intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='__funpolice__', intents=intents, help_command=None)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Command error: {error}")

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
    
    original_content = message.content
    new_content = detect_and_replace_words(original_content, forbidden)
    
    if new_content != original_content:
        try:
            await message.delete()
        except discord.Forbidden:
            print(f"Cannot delete message in {message.channel.name}. Ensure bot has 'Manage Messages' permission.")
            return
        
        webhook = await get_webhook(message.channel)
        if webhook:
            # Determine the avatar URL
            avatar_url = (message.author.guild_avatar.url if message.author.guild_avatar 
                         else message.author.avatar.url if message.author.avatar else None)
            
            # Handle replies
            if message.reference and message.reference.message_id:
                try:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                    
                    replied_content = replied_msg.content
                    if not replied_content:
                        replied_content = "*[message had no text content]*"
                    
                    if len(replied_content) > 100:
                        replied_content = replied_content[:100] + "..."
                    
                    if not replied_msg.author.bot:
                        quoted_text = f"> {replied_msg.author.mention}: {replied_content}"
                    else:
                        quoted_text = f"> **{replied_msg.author.display_name}:** {replied_content}"
                    
                    combined_content = f"{quoted_text}\n{new_content}"
                    
                    await webhook.send(
                        content=combined_content,
                        username=message.author.display_name,
                        avatar_url=avatar_url,
                        allowed_mentions=discord.AllowedMentions(users=[replied_msg.author])
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

# Server-specific autocomplete function
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

# Slash command to rename a filtered word
@app_commands.command(
    name="renamefilter",
    description="Rename a replacement category and move all associated words (admin only)."
)
@is_admin()
async def rename_filter(
    interaction: discord.Interaction,
    old_replacement: str,
    new_replacement: str
):
    """Rename a replacement category and move all associated words to the new replacement."""
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    config, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    old_replacement = old_replacement.strip()
    new_replacement = new_replacement.strip()

    if old_replacement not in config:
        await interaction.response.send_message(f"Replacement category '{old_replacement}' not found in {interaction.guild.name}.", ephemeral=True)
        return

    # Get all words from the old category
    old_words = config[old_replacement]
    if isinstance(old_words, str):
        old_words = [old_words]

    # Merge with new category if it exists
    if new_replacement in config:
        if isinstance(config[new_replacement], list):
            # Add only words not already present
            merged_words = config[new_replacement] + [w for w in old_words if w not in config[new_replacement]]
            config[new_replacement] = merged_words
        else:
            # Convert to list and merge
            existing_word = config[new_replacement]
            merged_words = [existing_word] + [w for w in old_words if w != existing_word]
            config[new_replacement] = merged_words
    else:
        config[new_replacement] = old_words

    # Remove the old category
    del config[old_replacement]

    save_server_config(interaction.guild.id, config, interaction.guild.name)
    await interaction.response.send_message(
        f"Renamed replacement category '{old_replacement}' to '{new_replacement}' and moved all associated words in {interaction.guild.name}.",
        ephemeral=True
    )    

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
        print(f"Error in slash command: {error}")
        await interaction.response.send_message("An error occurred while executing the command.", ephemeral=True)


# Add commands to the bot's command tree
bot.tree.add_command(add_filter)
bot.tree.add_command(delete_filter)
bot.tree.add_command(delete_replacement)
bot.tree.add_command(rename_filter)
bot.tree.add_command(list_filters)
bot.tree.add_command(reload_config)

# Run the bot
bot.run(BOT_TOKEN)