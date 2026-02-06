import discord
from discord import app_commands
from discord.ext import commands
import re
import json
import os
import time
import asyncio
import io
import uuid
from discord.ui import Button, View

# Generate Session ID
SESSION_ID = str(uuid.uuid4())[:8]

# Load secrets
with open('secrets.json', 'r') as f:
    secrets = json.load(f)
    BOT_TOKEN = secrets['BOT_TOKEN']

# Error logging function
def log_error(error: Exception, context: str = None):
    """Log errors to console with context"""
    error_msg = f"Error: {error}" if error else "Unknown error"
    if context:
        error_msg = f"{context} - {error_msg}"
    print(error_msg)
    # Could be extended to write to a file if needed:
    # with open('error.log', 'a') as f:
    #     f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {error_msg}\n")

# Ensure configs directory exists
CONFIGS_DIR = 'configs'
if not os.path.exists(CONFIGS_DIR):
    os.makedirs(CONFIGS_DIR)

# Leetspeak character mappings for normalization
LEETSPEAK_MAP = {
    '4': 'a', '@': 'a', '3': 'e', '1': 'i', '!': 'i', '0': 'o', '5': 's', '$': 's', '7': 't', '+': 't',
    '2': 'z', '6': 'g', '8': 'b', '9': 'g'
}

# Pre-compiled regex patterns
WORD_BOUNDARY_PATTERN = re.compile(r'\b')
NON_WORD_CHAR_PATTERN = re.compile(r'[^\w]')
SPACE_OR_SPECIAL = re.compile(r'\s*[^\w\s]*\s*')

# Configuration cache class
class ConfigCache:
    def __init__(self):
        self.configs = {}
        self.webhooks = {}
        self.cache_timeout = 300  # 5 minutes
        self.webhook_timeout = 3600  # 1 hour
        
    def get(self, guild_id: int, guild_name: str):
        cache_key = f"{guild_id}"
        cached = self.configs.get(cache_key)
        if cached and (time.time() - cached['timestamp']) < self.cache_timeout:
            return cached['config'], cached['forbidden'], cached.get('admin_config', {})
            
        config, forbidden, admin_config = load_server_config(guild_id, guild_name)
        self.configs[cache_key] = {
            'config': config,
            'forbidden': forbidden,
            'admin_config': admin_config,
            'timestamp': time.time()
        }
        return config, forbidden, admin_config
        
    def invalidate(self, guild_id: int):
        cache_key = f"{guild_id}"
        self.configs.pop(cache_key, None)
    
    async def get_webhook(self, channel):
        cache_key = f"{channel.guild.id}_{channel.id}"
        current_time = time.time()
        
        if (cache_key in self.webhooks and 
            current_time - self.webhooks[cache_key]['timestamp'] < self.webhook_timeout):
            return self.webhooks[cache_key]['webhook']
        
        webhook = await self._create_or_find_webhook(channel)
        if webhook:
            self.webhooks[cache_key] = {
                'webhook': webhook,
                'timestamp': current_time
            }
        return webhook
    
    async def _create_or_find_webhook(self, channel):
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.name == "WordFilterWebhook":
                    return wh
            return await channel.create_webhook(name="WordFilterWebhook")
        except discord.Forbidden:
            print(f"Cannot create webhook in {channel.name}. Ensure bot has 'Manage Webhooks' permission.")
            return None
    
    def cleanup_expired_cache(self):
        current_time = time.time()
        # Clean configs
        expired_configs = [
            k for k, v in self.configs.items() 
            if current_time - v['timestamp'] > self.cache_timeout
        ]
        for key in expired_configs:
            self.configs.pop(key, None)
            
        # Clean webhooks
        expired_webhooks = [
            k for k, v in self.webhooks.items() 
            if current_time - v['timestamp'] > self.webhook_timeout
        ]
        for key in expired_webhooks:
            self.webhooks.pop(key, None)

# WordFilter class for optimized regex patterns
class WordFilter:
    def __init__(self):
        self.patterns = {}
        self.pattern_timeout = 3600  # 1 hour pattern cache
        self.last_update = {}
    
    def get_pattern(self, word: str, replacement: str) -> list:
        cache_key = word
        current_time = time.time()
        
        # Check if pattern is cached and not expired
        if (cache_key in self.patterns and 
            current_time - self.last_update.get(cache_key, 0) < self.pattern_timeout):
            return self.patterns[cache_key]
            
        patterns = []
        
        # Basic word boundary pattern
        patterns.append((rf'\b{re.escape(word)}s?\b', word, False))
        
        if len(word) >= 3:
            # Combined leetspeak/wildcard/repeating pattern with looser character repeats
            leet_parts = []
            for i, char in enumerate(word):
                char_options = [char.upper(), char.lower()]
                # Add leetspeak alternatives
                for leet, normal in LEETSPEAK_MAP.items():
                    if normal == char.lower():
                        char_options.append(re.escape(leet))
                
                # Allow wildcards in middle positions
                if 0 < i < len(word) - 1:
                    char_options.extend(['*', '.', '-', '_', '#', '!', '?', '+', '='])
                
                # Build character pattern that allows unlimited repeats
                # Use + to allow any number of repeats
                char_pattern = f'[{"".join(re.escape(opt) for opt in char_options)}]'
                leet_parts.append(f'{char_pattern}+')
            
            patterns.append((r'\b' + ''.join(leet_parts) + r's?\b', word, True))
            
            # Spaced pattern
            spaced_parts = []
            for i, char in enumerate(word):
                if i > 0:
                    spaced_parts.append(r'\s*[^\w\s]*\s*')
                spaced_parts.append(f'[{char.upper()}{char.lower()}]')
            
            patterns.append((r'\b' + ''.join(spaced_parts) + r'(?:\s*[^\w\s]*\s*[sS])?' + r'\b', word, True))
        
        # Cache the patterns
        self.patterns[cache_key] = patterns
        self.last_update[cache_key] = current_time
        return patterns

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
    return os.path.join(CONFIGS_DIR, f'{guild_id}.json')

# Function to find existing config file (handles migration from old naming)
def find_existing_config(guild_id, guild_name=None):
    """Find existing config file, checking old naming conventions and migrating if needed"""
    # Try new naming convention first (guild_id only)
    new_filename = get_config_filename(guild_id, guild_name)
    if os.path.exists(new_filename):
        return new_filename

    # Check for old naming conventions and migrate them
    migration_candidates = []

    if guild_name:
        old_filename_1 = os.path.join(CONFIGS_DIR, f'{sanitize_filename(guild_name)}_{guild_id}.json')
        if os.path.exists(old_filename_1):
            migration_candidates.append(old_filename_1)

    old_filename_2 = os.path.join(CONFIGS_DIR, f'config_{guild_id}_{sanitize_filename(guild_name)}.json')
    if os.path.exists(old_filename_2):
        migration_candidates.append(old_filename_2)

    old_filename_3 = os.path.join(CONFIGS_DIR, f'config_{guild_id}.json')
    if os.path.exists(old_filename_3):
        migration_candidates.append(old_filename_3)

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
        return {"replacements": {}, "admin_config": {}}, {}, {}

    try:
        with open(existing_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Convert old format to new format if needed
        if not isinstance(config, dict) or "replacements" not in config:
            old_config = config
            config = {"replacements": {}, "admin_config": {}}
            for replacement, words in old_config.items():
                config["replacements"][replacement] = {
                    "words": [words] if isinstance(words, str) else words,
                    "whitelist": []
                }

        # Ensure admin_config exists
        if "admin_config" not in config:
            config["admin_config"] = {}

        # Store/update guild_name in config for display purposes
        if guild_name:
            config["guild_name"] = guild_name

    except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError):
        return {"replacements": {}, "admin_config": {}}, {}, {}

    # Build forbidden dictionary with whitelist support
    forbidden = {}
    for replacement, data in config["replacements"].items():
        words = data.get("words", [])
        whitelist = data.get("whitelist", [])
        if isinstance(words, str):
            words = [words]

        # Add each word to the forbidden dictionary with its whitelist
        for word in words:
            forbidden[word.lower()] = {
                "replacement": replacement,
                "whitelist": [w.lower() for w in whitelist]
            }

    return config, forbidden, config.get("admin_config", {})

# Function to save server-specific config
def save_server_config(guild_id, config, guild_name=None):
    new_filename = get_config_filename(guild_id, guild_name)
    temp_filename = f"{new_filename}.tmp"

    # Ensure config has the new format
    if "replacements" not in config:
        old_config = config
        config = {"replacements": {}}
        for replacement, words in old_config.items():
            config["replacements"][replacement] = {
                "words": [words] if isinstance(words, str) else words,
                "whitelist": []
            }

    # Store/update guild_name in config for display purposes
    if guild_name:
        config["guild_name"] = guild_name

    # Write to temporary file first
    try:
        with open(temp_filename, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        # Atomic rename with retry logic for Windows file locking
        retries = 5
        for i in range(retries):
            try:
                if os.path.exists(new_filename):
                    os.replace(temp_filename, new_filename)
                else:
                    os.rename(temp_filename, new_filename)
                break
            except (PermissionError, OSError) as e:
                if i == retries - 1:
                    raise e
                time.sleep(0.1)
                
    except Exception as e:
        # Clean up temp file if it exists
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except OSError:
                pass
        raise e
    finally:
        # Invalidate the cache for this guild
        config_cache.invalidate(guild_id)

# Function to suppress embeds in text by wrapping URLs in <>
def suppress_links(text):
    """Wrap URLs in <> to suppress embeds"""
    # Regex to find URLs not already wrapped in <>
    # This matches http/https URLs and wraps them in <...>
    return re.sub(r'(?<!<)(https?://[^\s]+)(?!>)', r'<\1>', text)

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
    """Detect and replace filtered words, handling various evasion techniques and whitelists"""
    if not forbidden:
        return content

    new_content = content
    matches_to_replace = []
    
    # For each forbidden word, use cached patterns with whitelist support
    for forbidden_word, filter_data in forbidden.items():
        replacement = filter_data["replacement"]
        whitelist = filter_data["whitelist"]
        
        # Get cached patterns for this word
        patterns = word_filter.get_pattern(forbidden_word, replacement)
        
        # Find all matches using the optimized patterns
        for pattern, base_word, is_evasion in patterns:
            try:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    matched_text = match.group(0)
                    match_start = match.start()
                    match_end = match.end()
                    
                    # Check if this match overlaps with any whitelisted phrase
                    skip_match = False
                    content_lower = content.lower()
                    for whitelisted in whitelist:
                        # Find all occurrences of the whitelisted phrase
                        for whitelist_match in re.finditer(re.escape(whitelisted.lower()), content_lower):
                            w_start = whitelist_match.start()
                            w_end = whitelist_match.end()
                            # Skip if there's any overlap
                            if not (match_end <= w_start or match_start >= w_end):
                                skip_match = True
                                break
                        if skip_match:
                            break
                    if skip_match:
                        continue
                    
                    # Simple validation for evasion attempts
                    if is_evasion:
                        # Remove word boundaries and check if it's reasonable
                        clean_match = re.sub(r'[^\w]', '', matched_text.lower())
                        clean_target = base_word.lower()
                        
                        # Must have at least 50% of the original letters
                        matching_chars = sum(1 for c in clean_match if c in clean_target)
                        if len(clean_match) > 0 and matching_chars / len(clean_target) < 0.5:
                            continue
                        
                        # Special handling for repeated characters
                        # First, collapse repeated characters (e.g., "niggggger" -> "niger")
                        collapsed_match = re.sub(r'(.)\1+', r'\1', clean_match)
                        collapsed_target = re.sub(r'(.)\1+', r'\1', clean_target)
                        
                        # If the collapsed versions don't match in length (+/- 2 chars), 
                        # and the original isn't just repeating a letter from the target,
                        # then it's probably a false positive
                        if (len(collapsed_match) > len(collapsed_target) + 2 and
                            not any(c * 2 in clean_target for c in set(clean_match))):
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

# Helper to parse duration string
def parse_duration(duration_str):
    if not duration_str: return None
    match = re.match(r'(\d+)([dhms])', duration_str.lower())
    if not match: return None
    val, unit = match.groups()
    val = int(val)
    if unit == 'd': return val * 86400
    if unit == 'h': return val * 3600
    if unit == 'm': return val * 60
    if unit == 's': return val
    return None

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

# Set up the bot with intents and caches
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='__funpolice__', intents=intents, help_command=None)

# Initialize caches
config_cache = ConfigCache()
word_filter = WordFilter()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Command error: {error}")

# Message processing functions
def should_process_message(message):
    return not message.author.bot and message.guild is not None

async def handle_reply(message, new_content):
    if not message.reference or not message.reference.message_id:
        return (new_content, None)
        
    try:
        replied_msg = await message.channel.fetch_message(message.reference.message_id)
        if not replied_msg:
            return (new_content, None)

        replied_content = replied_msg.content or "*[message had no text content]*"
        replied_content = suppress_links(replied_content)
        replied_content = replied_content[:100] + "..." if len(replied_content) > 100 else replied_content
        
        prefix = f"> {replied_msg.author.mention}" if not replied_msg.author.bot else f"> **{replied_msg.author.display_name}**"
        return (f"{prefix}: {replied_content}\n{new_content}", replied_msg.author)
    except discord.NotFound:
        log_error(None, f"Referenced message {message.reference.message_id} not found")
        return (new_content, None)
    except discord.Forbidden:
        log_error(None, f"No permission to fetch message {message.reference.message_id}")
        return (new_content, None)
    except Exception as e:
        log_error(e, f"Error handling reply to message {message.reference.message_id}")
        return (new_content, None)

async def send_filtered_message_with_attachments(message, webhook, new_content, downloaded_attachments, skipped_attachments=None):
    try:
        avatar_url = (message.author.guild_avatar.url if message.author.guild_avatar 
                    else message.author.avatar.url if message.author.avatar else None)
        
        content = new_content
        
        # Add simple notice about skipped attachments
        if skipped_attachments:
            too_large_count = sum(1 for s in skipped_attachments if s['reason'] == 'too_large')
            failed_count = len(skipped_attachments) - too_large_count
            
            notices = []
            if too_large_count > 0:
                notices.append("*Attached file too large to repost (8MB limit)*")
            if failed_count > 0:
                notices.append("*Some attachments failed to process*")
            
            if notices:
                content += "\n\n" + "\n".join(notices)
        
        # Handle reply processing
        reply_user = None
        if message.reference and message.reference.message_id:
            try:
                replied_msg = await message.channel.fetch_message(message.reference.message_id)
                if replied_msg:
                    replied_content = replied_msg.content or "*[message had no text content]*"
                    replied_content = suppress_links(replied_content)
                    replied_content = replied_content[:100] + "..." if len(replied_content) > 100 else replied_content
                    
                    prefix = f"> {replied_msg.author.mention}" if not replied_msg.author.bot else f"> **{replied_msg.author.display_name}**"
                    content = f"{prefix}: {replied_content}\n{content}"
                    reply_user = replied_msg.author
            except Exception as e:
                log_error(e, f"Error handling reply to message {message.reference.message_id}")
        
        # Convert downloaded attachments to discord.File objects
        files = []
        for attachment_data in downloaded_attachments:
            try:
                discord_file = discord.File(
                    io.BytesIO(attachment_data['data']), 
                    filename=attachment_data['filename'],
                    spoiler=attachment_data['spoiler']
                )
                files.append(discord_file)
            except Exception as e:
                log_error(e, f"Failed to create discord.File for {attachment_data['filename']}")
                continue
        
        await webhook.send(
            content=content,
            username=message.author.display_name,
            avatar_url=avatar_url,
            files=files,
            allowed_mentions=discord.AllowedMentions(
                users=[reply_user] if reply_user else [],
                everyone=False,
                roles=False
            )
        )
    except Exception as e:
        log_error(e, f"Error sending filtered message in {message.channel.name}")
        # Fallback to basic message without attachments if everything fails
        try:
            await webhook.send(
                content=new_content,
                username=message.author.display_name,
                avatar_url=avatar_url,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False)
            )
        except Exception as fallback_error:
            log_error(fallback_error, f"Fallback message also failed in {message.channel.name}")

# Event handler for new messages
@bot.event
async def on_message(message):
    if not should_process_message(message):
        return

    # Load server-specific config from cache
    config, forbidden, _ = config_cache.get(message.guild.id, message.guild.name)
    if not forbidden:
        return
    
    # print(f"[DEBUG] Checking message {message.id} in {message.guild.name}: {message.content[:20]}...")
    
    new_content = detect_and_replace_words(message.content, forbidden)
    if new_content == message.content:
        return
        
    print(f"[DEBUG] Filter matched for message {message.id}. New content length: {len(new_content)}")
    
    # Download attachments BEFORE deleting the message
    print(f"[DEBUG] Processing message {message.id} from {message.author} in {message.channel}. Has attachments: {bool(message.attachments)}")
    downloaded_attachments = []
    skipped_attachments = []
    MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB in bytes
    
    if message.attachments:
        print(f"[DEBUG] Starting attachment download for message {message.id}")
        for attachment in message.attachments:
            try:
                # Check file size before downloading
                if attachment.size > MAX_FILE_SIZE:
                    print(f"Skipping {attachment.filename} - too large ({attachment.size / (1024*1024):.1f}MB)")
                    skipped_attachments.append({
                        'filename': attachment.filename,
                        'size': attachment.size,
                        'reason': 'too_large'
                    })
                    continue
                
                # Download the attachment data
                file_data = await attachment.read()
                downloaded_attachments.append({
                    'data': file_data,
                    'filename': attachment.filename,
                    'spoiler': attachment.is_spoiler()
                })
            except Exception as e:
                log_error(e, f"Failed to download attachment {attachment.filename}")
                skipped_attachments.append({
                    'filename': attachment.filename,
                    'size': attachment.size,
                    'reason': 'download_failed'
                })
                continue
    
    # Now delete the original message
    try:
        print(f"[DEBUG] Attempting to delete message {message.id}")
        await message.delete()
        print(f"[DEBUG] Successfully deleted message {message.id}")
    except discord.NotFound:
        print(f"[DEBUG] Message {message.id} not found during delete (already deleted?) - continuing to repost")
    except discord.Forbidden:
        print(f"Cannot delete message in {message.channel.name}. Ensure bot has 'Manage Messages' permission.")
        return
    except Exception as e:
        print(f"[DEBUG] Unexpected error deleting message {message.id}: {e}")
        # If we can't delete it, we should probably stop? Or continue? 
        # If we continue, we might duplicate the message (original + filtered).
        # But if the error is "system error", maybe we should try to continue.
        # For now, let's catch generic to avoid crashing the event handler, but maybe return?
        # The user's specific error was NotFound, so handling that is priority.
        pass # Continuing for now

    # Get webhook and send the filtered message with attachments
    print(f"[DEBUG] Attempting to repost filtered message for {message.id}")
    webhook = await config_cache.get_webhook(message.channel)
    if webhook:
        await send_filtered_message_with_attachments(message, webhook, new_content, downloaded_attachments, skipped_attachments)
    else:
        print(f"[DEBUG] Failed to get/create webhook for {message.channel.id}")

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
    
    config, _, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    
    if not config or "replacements" not in config:
        return []
        
    replacements = list(config["replacements"].keys())
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
    config, forbidden, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    
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
    if "replacements" not in config:
        config["replacements"] = {}
        
    if replacement in config["replacements"]:
        current_words = config["replacements"][replacement].get("words", [])
        if isinstance(current_words, str):
            current_words = [current_words]
            
        # Add new words if they don't exist
        for word in word_list:
            if word not in current_words:
                current_words.append(word)
                added_words.append(word)
            else:
                already_filtered.append(word)
                
        config["replacements"][replacement]["words"] = current_words
    else:
        config["replacements"][replacement] = {
            "words": word_list,
            "whitelist": []
        }
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
    config, forbidden, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    
    word = word.lower().strip()
    found = False
    
    # Search for the word in config
    if "replacements" in config:
        for replacement, data in list(config["replacements"].items()):
            words = data.get("words", [])
            if isinstance(words, str):
                words = [words]
            if word in words:
                # If it's a single word, remove the whole category
                if isinstance(data["words"], str) or len(data["words"]) == 1:
                    del config["replacements"][replacement]
                else:
                    # Remove the word from the list
                    data["words"].remove(word)
                    # Remove category if no words left
                    if not data["words"]:
                        del config["replacements"][replacement]
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
    config, forbidden, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    
    replacement = replacement.strip()
    
    # Check if the replacement exists in the config
    if "replacements" not in config or replacement not in config["replacements"]:
        await interaction.response.send_message(f"Replacement category '{replacement}' not found in {interaction.guild.name}.", ephemeral=True)
        return
    
    # Get the words for confirmation message

    data = config["replacements"][replacement]
    words = data.get("words", [])
    if isinstance(words, str):
        words = [words]
    word_count = len(words)
    words_str = ", ".join(words)
    
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
        config, forbidden, _ = load_server_config(interaction.guild.id, interaction.guild.name)
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
    
    config, forbidden, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    
    if not config:
        await interaction.response.send_message(f"No filters found for {interaction.guild.name}.", ephemeral=True)
        return
    
    # Create pages (5 categories per page)
    items_per_page = 5
    replacements = list(config.get("replacements", {}).items())
    pages = []
    
    for i in range(0, len(replacements), items_per_page):
        embed = discord.Embed(title=f"Word Filters - {interaction.guild.name}", color=0x00ff00)
        embed.set_footer(text=f"Page {i // items_per_page + 1} of {(len(replacements) - 1) // items_per_page + 1}")
        
        for replacement, data in replacements[i:i + items_per_page]:
            # Get words list and format it nicely
            words = data.get("words", [])
            if isinstance(words, str):
                words = [words]
            words_str = ", ".join(f"`{word}`" for word in words)
            
            # Get whitelist if any
            whitelist = data.get("whitelist", [])
            if whitelist:
                whitelist_str = "\nWhitelist: " + ", ".join(f"`{w}`" for w in whitelist)
            else:
                whitelist_str = ""
            
            # Add field to embed with proper formatting
            value = f"{words_str}{whitelist_str}"
            if len(value) > 1024:  # Discord embed field value limit
                value = value[:1021] + "..."
                
            embed.add_field(name=f"➜ {replacement}", value=value, inline=False)
            
        pages.append(embed)

    if not pages:  # Create empty state page
        embed = discord.Embed(
            title=f"Word Filters - {interaction.guild.name}",
            description="No filters configured.",
            color=0x00ff00
        )
        pages = [embed]
    
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

    config, _, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    old_replacement = old_replacement.strip()
    new_replacement = new_replacement.strip()

    if "replacements" not in config or old_replacement not in config["replacements"]:
        await interaction.response.send_message(f"Replacement category '{old_replacement}' not found in {interaction.guild.name}.", ephemeral=True)
        return
    
    # Get all words from the old category
    old_data = config["replacements"][old_replacement]
    old_words = old_data.get("words", [])
    old_whitelist = old_data.get("whitelist", [])
    if isinstance(old_words, str):
        old_words = [old_words]

    # Prepare new category data
    new_data = {
        "words": old_words,
        "whitelist": old_whitelist
    }

    # Merge with new category if it exists
    if new_replacement in config["replacements"]:
        existing_data = config["replacements"][new_replacement]
        existing_words = existing_data.get("words", [])
        existing_whitelist = existing_data.get("whitelist", [])
        
        if isinstance(existing_words, str):
            existing_words = [existing_words]
        
        # Merge words and whitelist, avoiding duplicates
        merged_words = existing_words + [w for w in old_words if w not in existing_words]
        merged_whitelist = existing_whitelist + [w for w in old_whitelist if w not in existing_whitelist]
        
        config["replacements"][new_replacement] = {
            "words": merged_words,
            "whitelist": merged_whitelist
        }
    else:
        config["replacements"][new_replacement] = new_data

    # Remove the old category
    del config["replacements"][old_replacement]

    save_server_config(interaction.guild.id, config, interaction.guild.name)
    await interaction.response.send_message(
        f"Renamed replacement category '{old_replacement}' to '{new_replacement}' and moved all associated words in {interaction.guild.name}.",
        ephemeral=True
    )    

# --- Administrative Features ---

# Slash command to configure join role
@app_commands.command(
    name="joinrole",
    description="Configure the auto-role assignment for new members (admin only)."
)
@is_admin()
async def join_role_config(
    interaction: discord.Interaction,
    join_role: discord.Role,
    user_role: discord.Role = None,
    duration: str = None
):
    """
    Configure the role assigned when a user joins.
    - join_role: The role given immediately on join.
    - user_role: (Optional) The role given after the duration expires.
    - duration: (Optional) How long to keep the join role (e.g., '3d', '12h'). Defaults to 3d if user_role is set.
    """
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # Load config
    config, _, admin_config = load_server_config(interaction.guild.id, interaction.guild.name)
    
    # Process inputs
    duration_seconds = None
    if user_role:
        if duration:
            duration_seconds = parse_duration(duration)
            if not duration_seconds:
                await interaction.response.send_message("Invalid duration format. Use '3d', '12h', '30m', etc.", ephemeral=True)
                return
        else:
            duration_seconds = 3 * 86400  # Default 3 days
    
    # Update config
    if "join_system" not in admin_config:
        admin_config["join_system"] = {}
        
    admin_config["join_system"] = {
        "join_role_id": join_role.id,
        "user_role_id": user_role.id if user_role else None,
        "duration_seconds": duration_seconds,
        "enabled": True
    }
    
    config["admin_config"] = admin_config
    save_server_config(interaction.guild.id, config, interaction.guild.name)
    
    # Response
    msg = f"✅ Join role set to {join_role.mention}."
    if user_role:
        if duration_seconds >= 86400:
            val = duration_seconds / 86400
            unit = "days"
        elif duration_seconds >= 3600:
            val = duration_seconds / 3600
            unit = "hours"
        elif duration_seconds >= 60:
            val = duration_seconds / 60
            unit = "minutes"
        else:
            val = duration_seconds
            unit = "seconds"
            
        # Format to remove .0 if it's a whole number
        val_str = f"{val:.1f}"
        if val_str.endswith('.0'):
            val_str = val_str[:-2]
            
        msg += f"\nMembers will be promoted to {user_role.mention} after {val_str} {unit}."
    else:
        msg += "\nNo auto-promotion configured (members keep the role indefinitely)."
        
    await interaction.response.send_message(msg, ephemeral=True)

# Event handler for member join
@bot.event
async def on_member_join(member):
    try:
        _, _, admin_config = config_cache.get(member.guild.id, member.guild.name)
        
        # Check for jail evasion
        jail_system = admin_config.get("jail_system", {})
        jailed_users = jail_system.get("jailed_users", {})
        jail_role_id = jail_system.get("jail_role_id")
        
        if str(member.id) in jailed_users and jail_role_id:
            jail_role = member.guild.get_role(jail_role_id)
            if jail_role:
                await member.add_roles(jail_role, reason="Re-jailed on join (evasion attempt)")
                print(f"Re-jailed evasion attempt: {member.display_name} in {member.guild.name}")
                return  # Skip join role assignment for jailed users

        # Join Role Logic
        join_system = admin_config.get("join_system", {})
        
        if not join_system.get("enabled", False):
            return
            
        join_role_id = join_system.get("join_role_id")
        if not join_role_id:
            return
            
        role = member.guild.get_role(join_role_id)
        if role:
            await member.add_roles(role, reason="Auto-role on join")
            print(f"Assigned join role {role.name} to {member.display_name} in {member.guild.name}")
        else:
            print(f"Join role ID {join_role_id} not found in {member.guild.name}")
            
    except Exception as e:
        log_error(e, f"Error in on_member_join for {member.guild.name}")

# Event handler for member updates (roles) to handle manual jail/unjail
@bot.event
async def on_member_update(before, after):
    if before.roles == after.roles:
        return
        
    try:
        guild = after.guild
        # We need the full config object for saving, but we can read from cache first
        # Actually for updates that lead to saves, we probably want fresh config anyway to avoid race conditions
        # But for the initial check (is jail configured?), cache is fine.
        # However, since we might WRITE, we should eventually load fresh.
        # Let's stick to load_server_config for the WRITE path to be safe,
        # but we can optimize the early exit?
        # Given this event fires OFTEN, optimization is good.
        
        _, _, cached_admin = config_cache.get(guild.id, guild.name)
        if not cached_admin.get("jail_system", {}).get("jail_role_id"):
             return

        # Now load fresh for the actual logic to ensure we don't overwrite concurrent changes
        config, _, admin_config = load_server_config(guild.id, guild.name)
        jail_system = admin_config.get("jail_system", {})
        jail_role_id = jail_system.get("jail_role_id")
        
        if not jail_role_id:
            return
            
        jail_role = guild.get_role(jail_role_id)
        if not jail_role:
            return
            
        # Check if jail role was added or removed
        was_jailed = jail_role in before.roles
        is_jailed = jail_role in after.roles
        
        # Manual Jail Detection (Role added, but user not in DB yet)
        if not was_jailed and is_jailed:
            jailed_users = jail_system.get("jailed_users", {})
            user_id_str = str(after.id)
            
            # Only process if not already known to be jailed (avoids loop with /jail command)
            if user_id_str not in jailed_users:
                print(f"Manual jail detected for {after.display_name}")
                
                # Save previous roles (excluding managed/everyone and the jail role itself)
                saved_roles = [r.id for r in before.roles
                              if not r.is_default() and not r.managed and r.id != jail_role_id]
                
                jailed_users[user_id_str] = saved_roles
                jail_system["jailed_users"] = jailed_users
                config["admin_config"]["jail_system"] = jail_system
                save_server_config(guild.id, config, guild.name)
                
                # Strip other roles
                roles_to_keep = [jail_role]
                # We might need to keep other managed roles that we can't remove
                for r in after.roles:
                    if r.managed or r.is_default():
                        roles_to_keep.append(r)
                
                # Only edit if we actually need to remove something
                if len(after.roles) > len(roles_to_keep):
                    await after.edit(roles=roles_to_keep, reason="Manual Jail - Stripping roles")

        # Manual Unjail Detection (Role removed, and user IS in DB)
        elif was_jailed and not is_jailed:
            jailed_users = jail_system.get("jailed_users", {})
            user_id_str = str(after.id)
            
            if user_id_str in jailed_users:
                print(f"Manual unjail detected for {after.display_name}")
                
                # Restore roles
                saved_role_ids = jailed_users[user_id_str]
                roles_to_add = []
                for rid in saved_role_ids:
                    r = guild.get_role(rid)
                    if r:
                        roles_to_add.append(r)
                
                # Remove from DB
                del jailed_users[user_id_str]
                jail_system["jailed_users"] = jailed_users
                config["admin_config"]["jail_system"] = jail_system
                save_server_config(guild.id, config, guild.name)
                
                # Apply roles
                if roles_to_add:
                    await after.add_roles(*roles_to_add, reason="Manual Unjail - Restoring roles")

    except Exception as e:
        log_error(e, f"Error in on_member_update for {after.guild.name}")

# Background task to check for role promotion
async def check_join_roles_task():
    while True:
        try:
            await asyncio.sleep(900)  # Check every 15 minutes
            
            for guild in bot.guilds:
                try:
                    # Use cache for read-only background task
                    _, _, admin_config = config_cache.get(guild.id, guild.name)
                    join_system = admin_config.get("join_system", {})
                    
                    if not join_system.get("enabled", False):
                        continue
                        
                    join_role_id = join_system.get("join_role_id")
                    user_role_id = join_system.get("user_role_id")
                    duration = join_system.get("duration_seconds")
                    
                    if not (join_role_id and user_role_id and duration):
                        continue
                        
                    join_role = guild.get_role(join_role_id)
                    user_role = guild.get_role(user_role_id)
                    
                    if not (join_role and user_role):
                        continue
                        
                    # Check members with the join role
                    current_time = time.time()
                    for member in join_role.members:
                        # Skip if they already have the user role
                        if user_role in member.roles:
                            continue
                            
                        # Check time in role (using joined_at as proxy since we add it on join)
                        if member.joined_at:
                            joined_ts = member.joined_at.timestamp()
                            if current_time - joined_ts > duration:
                                try:
                                    await member.remove_roles(join_role, reason="Join role expired")
                                    await member.add_roles(user_role, reason="Promoted from join role")
                                    print(f"Promoted {member.display_name} in {guild.name}")
                                except discord.Forbidden:
                                    print(f"Permission error promoting {member.display_name} in {guild.name}")
                                except Exception as e:
                                    log_error(e, f"Error promoting {member.display_name}")
                                    
                except Exception as e:
                    log_error(e, f"Error processing join roles for guild {guild.id}")
                    
        except Exception as e:
            log_error(e, "Fatal error in check_join_roles_task")
            await asyncio.sleep(60)

# Periodic cache cleanup task
async def cleanup_cache_task():
    while True:
        await asyncio.sleep(300)  # Run every 5 minutes
        try:
            config_cache.cleanup_expired_cache()
        except Exception as e:
            print(f"Error during cache cleanup: {e}")

# Setup hook for initialization
async def setup_hook():
    # Start cache cleanup task
    bot.loop.create_task(cleanup_cache_task())
    # Start join role checker
    bot.loop.create_task(check_join_roles_task())

# Add setup hook to bot
bot.setup_hook = setup_hook

# Sync commands on startup
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
        config, forbidden, _ = load_server_config(self.guild_id, self.guild_name)
        
        # Get word count for confirmation message
        data = config.get("replacements", {}).get(self.replacement, {})
        words = data.get("words", [])
        if isinstance(words, str):
            words = [words]
        word_count = len(words)
        
        # Delete the category
        if "replacements" in config and self.replacement in config["replacements"]:
            del config["replacements"][self.replacement]
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
        msg = "You need administrator permissions to use this command."
    else:
        print(f"Error in slash command: {error}")
        msg = "An error occurred while executing the command."
        
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


# Slash command to add whitelist entries
@app_commands.command(
    name="addwhitelist",
    description="Add whitelist phrases for a filtered word (admin only)."
)
@is_admin()
@app_commands.autocomplete(replacement=replacement_autocomplete)
async def add_whitelist(
    interaction: discord.Interaction,
    replacement: str,
    phrases: str
):
    """Add whitelist phrases for a filtered word category.
    Separate phrases with commas."""
    
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    
    config, _, _ = load_server_config(interaction.guild.id, interaction.guild.name)
    replacement = replacement.strip()
    
    if "replacements" not in config or replacement not in config["replacements"]:
        await interaction.response.send_message(
            f"Replacement category '{replacement}' not found in {interaction.guild.name}.",
            ephemeral=True
        )
        return
    
    # Split and clean phrases
    phrase_list = [phrase.lower().strip() for phrase in phrases.split(',') if phrase.strip()]
    
    if not phrase_list:
        await interaction.response.send_message("No valid phrases provided.", ephemeral=True)
        return
    
    # Get current whitelist or create it
    current_whitelist = config["replacements"][replacement].get("whitelist", [])
    added_phrases = []
    already_whitelisted = []
    
    # Add new phrases
    for phrase in phrase_list:
        if phrase not in current_whitelist:
            current_whitelist.append(phrase)
            added_phrases.append(phrase)
        else:
            already_whitelisted.append(phrase)
    
    # Update config
    config["replacements"][replacement]["whitelist"] = current_whitelist
    save_server_config(interaction.guild.id, config, interaction.guild.name)
    
    # Prepare response
    response = []
    if added_phrases:
        response.append(f"Added {len(added_phrases)} phrase(s) to whitelist for '{replacement}' in {interaction.guild.name}:")
        response.append(", ".join(f"'{phrase}'" for phrase in added_phrases))
    
    if already_whitelisted:
        whitelisted_phrases = [f"'{p}'" for p in already_whitelisted]
        response.append(f"These phrases were already whitelisted: {', '.join(whitelisted_phrases)}")
    
    await interaction.response.send_message("\n".join(response), ephemeral=True)

# Add commands to the bot's command tree
bot.tree.add_command(add_filter)
bot.tree.add_command(delete_filter)
bot.tree.add_command(delete_replacement)
bot.tree.add_command(rename_filter)
bot.tree.add_command(list_filters)
bot.tree.add_command(reload_config)
bot.tree.add_command(add_whitelist)
bot.tree.add_command(join_role_config)

# Slash command to configure jail role
@app_commands.command(
    name="setjailrole",
    description="Set the role used for jailing users (admin only)."
)
@is_admin()
async def set_jail_role(
    interaction: discord.Interaction,
    role: discord.Role
):
    """Set the jail role."""
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    config, _, admin_config = load_server_config(interaction.guild.id, interaction.guild.name)
    
    if "jail_system" not in admin_config:
        admin_config["jail_system"] = {}
        
    admin_config["jail_system"]["jail_role_id"] = role.id
    # Ensure jailed_users dict exists
    if "jailed_users" not in admin_config["jail_system"]:
        admin_config["jail_system"]["jailed_users"] = {}
        
    config["admin_config"] = admin_config
    save_server_config(interaction.guild.id, config, interaction.guild.name)
    
    await interaction.response.send_message(f"✅ Jail role set to {role.mention}.", ephemeral=True)

# Slash command to jail a user
@app_commands.command(
    name="jail",
    description="Jail a user, stripping their roles."
)
@app_commands.default_permissions(manage_roles=True)
@app_commands.describe(reason="The reason for jailing (visible to everyone)")
async def jail_user(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = None
):
    """Jail a user."""
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # Defer response as this might take a moment
    await interaction.response.defer(ephemeral=False)

    config, _, admin_config = load_server_config(interaction.guild.id, interaction.guild.name)
    jail_system = admin_config.get("jail_system", {})
    jail_role_id = jail_system.get("jail_role_id")
    
    if not jail_role_id:
        await interaction.followup.send("❌ No jail role configured. Use /setjailrole first.")
        return
        
    jail_role = interaction.guild.get_role(jail_role_id)
    if not jail_role:
        await interaction.followup.send("❌ Configured jail role no longer exists.")
        return

    # Check if already jailed
    jailed_users = jail_system.get("jailed_users", {})
    if str(user.id) in jailed_users:
        await interaction.followup.send(f"{user.mention} is already jailed.")
        return
        
    # Save roles
    saved_roles = [r.id for r in user.roles
                  if not r.is_default() and not r.managed and r.id != jail_role_id]
    
    # Update DB first (to prevent manual-jail detection in on_member_update)
    jailed_users[str(user.id)] = saved_roles
    jail_system["jailed_users"] = jailed_users
    # Ensure config structure is complete
    if "jail_system" not in admin_config: admin_config["jail_system"] = jail_system
    config["admin_config"] = admin_config
    save_server_config(interaction.guild.id, config, interaction.guild.name)
    
    try:
        # Strip roles and add jail role
        roles_to_keep = [jail_role]
        for r in user.roles:
            if r.managed or r.is_default():
                roles_to_keep.append(r)
        
        reason_text = reason or "No reason provided"
        await user.edit(roles=roles_to_keep, reason=f"Jailed by {interaction.user.display_name}: {reason_text}")
        await interaction.followup.send(f"🚨 {user.mention} has been jailed.\n**Reason:** {reason_text}")
        
    except discord.Forbidden:
        # Rollback DB if permission error
        del jailed_users[str(user.id)]
        save_server_config(interaction.guild.id, config, interaction.guild.name)
        await interaction.followup.send("❌ Failed to jail user: Missing permissions (Bot role must be higher than user role).")
    except Exception as e:
        log_error(e, "Error executing jail command")
        await interaction.followup.send("❌ An unexpected error occurred.")

# Slash command to unjail a user
@app_commands.command(
    name="unjail",
    description="Unjail a user and restore their roles."
)
@app_commands.default_permissions(manage_roles=True)
async def unjail_user(
    interaction: discord.Interaction,
    user: discord.Member
):
    """Unjail a user."""
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    config, _, admin_config = load_server_config(interaction.guild.id, interaction.guild.name)
    jail_system = admin_config.get("jail_system", {})
    jailed_users = jail_system.get("jailed_users", {})
    
    if str(user.id) not in jailed_users:
        await interaction.followup.send(f"{user.mention} is not currently jailed (according to bot records).")
        return
        
    # Get saved roles
    saved_role_ids = jailed_users[str(user.id)]
    roles_to_add = []
    for rid in saved_role_ids:
        r = interaction.guild.get_role(rid)
        if r:
            roles_to_add.append(r)
            
    jail_role_id = jail_system.get("jail_role_id")
    jail_role = interaction.guild.get_role(jail_role_id) if jail_role_id else None
            
    try:
        # Update DB first (to prevent manual-unjail detection)
        del jailed_users[str(user.id)]
        save_server_config(interaction.guild.id, config, interaction.guild.name)
        
        # Restore roles and remove jail role
        await user.add_roles(*roles_to_add, reason=f"Unjailed by {interaction.user.display_name}")
        
        if jail_role and jail_role in user.roles:
            await user.remove_roles(jail_role, reason="Unjail")
            
        await interaction.followup.send(f"🕊️ {user.mention} has been released.")
        
    except discord.Forbidden:
        await interaction.followup.send("❌ Failed to unjail user: Missing permissions.")
    except Exception as e:
        log_error(e, "Error executing unjail command")
        await interaction.followup.send("❌ An unexpected error occurred.")

# Add commands to tree
bot.tree.add_command(set_jail_role)
bot.tree.add_command(jail_user)
bot.tree.add_command(unjail_user)

# Error handling system
class BotError(Exception):
    """Base error class for bot-specific errors"""
    pass

class ConfigError(BotError):
    """Configuration related errors"""
    pass

class WebhookError(BotError):
    """Webhook related errors"""
    pass

def log_error(error, context=None):
    """Centralized error logging"""
    error_msg = f"{type(error).__name__}: {str(error)}"
    if context:
        error_msg = f"{context}: {error_msg}"
    print(error_msg)  # Could be replaced with proper logging

# Periodic cache cleanup
async def cleanup_cache_task():
    while True:
        await asyncio.sleep(300)  # Run every 5 minutes
        config_cache.cleanup_expired_cache()

# Run the bot with proper error handling
try:
    bot.run(BOT_TOKEN)
except KeyboardInterrupt:
    print("\nBot shutdown by user")
except Exception as e:
    log_error(e, "Fatal error")