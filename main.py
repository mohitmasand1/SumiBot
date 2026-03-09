import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

EST = ZoneInfo("America/New_York")
SCHEDULES_FILE = "schedules.json"

# --- Config ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Error: DISCORD_TOKEN not set. Add it to your .env file.")

# --- Bot setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --- Helper ---
def has_permission(member: discord.Member) -> bool:
    """Check if the member has Manage Messages permission."""
    return member.guild_permissions.manage_messages

async def silent(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.delete_original_response()

# --- Schedule persistence ---
def load_schedules() -> list:
    """Load scheduled messages from disk."""
    if os.path.exists(SCHEDULES_FILE):
        with open(SCHEDULES_FILE, "r") as f:
            return json.load(f)
    return []

def save_schedules(schedules: list):
    """Save scheduled messages to disk."""
    with open(SCHEDULES_FILE, "w") as f:
        json.dump(schedules, f, indent=2)

def next_schedule_id(schedules: list) -> int:
    """Return the next available schedule ID."""
    return max((s["id"] for s in schedules), default=0) + 1

def compute_next_run(start_date: str, time_str: str) -> datetime:
    """Build a timezone-aware datetime in EST from date + time strings."""
    dt = datetime.strptime(f"{start_date} {time_str}", "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=EST)

# --- On ready ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if not schedule_loop.is_running():
        schedule_loop.start()

# --- Manual sync (owner only, avoids rate limits) ---
@bot.command()
@commands.is_owner()
async def sync(ctx):
    synced = await tree.sync()
    await ctx.send(f"✅ Synced {len(synced)} commands.")

# ============================================================
# SLASH COMMANDS
# ============================================================

# --- /say (inline for single line, modal for multiline) ---
@tree.command(name="say", description="Send a message as Sumi Bot in this channel")
@app_commands.describe(
    message="Message to send (leave empty to open multiline editor)",
    image="Image to attach to the message"
)
async def say(interaction: discord.Interaction, message: str = None, image: discord.Attachment = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return

    # If message or image provided inline, send directly
    if message or image:
        file = await image.to_file() if image else None
        await interaction.channel.send(content=message, file=file)
        await silent(interaction)
        return

    # Otherwise open modal for multiline (modals cannot include file uploads)
    channel = interaction.channel

    class SayModal(discord.ui.Modal, title="Send Message as Bot"):
        message_input = discord.ui.TextInput(
            label="Message",
            style=discord.TextStyle.paragraph,
            placeholder="Type your message here... (supports multiple lines)",
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            await channel.send(self.message_input.value)
            await modal_interaction.response.send_message("_ _", ephemeral=True)
            await modal_interaction.delete_original_response()

    await interaction.response.send_modal(SayModal())

# --- /edit ---
@tree.command(name="edit", description="Edit a previous bot message in this channel")
@app_commands.describe(
    message_id="ID of the bot message to edit",
    new_content="New message content",
    image="New image to attach (replaces existing attachments)"
)
async def edit(interaction: discord.Interaction, message_id: str, new_content: str = None, image: discord.Attachment = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    if not new_content and not image:
        await interaction.response.send_message("❌ Provide new content, a new image, or both.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        if target.author != bot.user:
            await interaction.response.send_message("❌ I can only edit my own messages.", ephemeral=True)
            return
        kwargs = {}
        if new_content is not None:
            kwargs["content"] = new_content
        if image:
            kwargs["attachments"] = [await image.to_file()]
        await target.edit(**kwargs)
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)

# --- /delete ---
@tree.command(name="delete", description="Delete a bot message in this channel")
@app_commands.describe(message_id="ID of the bot message to delete")
async def delete(interaction: discord.Interaction, message_id: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        if target.author != bot.user:
            await interaction.response.send_message("❌ I can only delete my own messages.", ephemeral=True)
            return
        await target.delete()
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)

# --- /reply (slash command with image support) ---
@tree.command(name="reply", description="Reply to a message as Sumi Bot")
@app_commands.describe(
    message_id="ID of the message to reply to",
    message="Text content of the reply",
    image="Image to attach to the reply"
)
async def reply(interaction: discord.Interaction, message_id: str, message: str = None, image: discord.Attachment = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    if not message and not image:
        await interaction.response.send_message("❌ Provide a message, an image, or both.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        file = await image.to_file() if image else None
        await target.reply(content=message, file=file)
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)

# --- /help ---
@tree.command(name="help", description="List all available Sumi Bot commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖  Sumi Bot — Commands",
        color=discord.Color.blurple(),
    )

    embed.add_field(name="📢  Messaging", value=(
        "`/say` — Send a message as Sumi Bot (inline or multiline modal). Supports image attachment.\n"
        "`/edit` — Edit a previous bot message by ID. Supports updating text and/or image.\n"
        "`/delete` — Delete a bot message by ID.\n"
        "`/reply` — Reply to any message by ID as Sumi Bot. Supports image attachment."
    ), inline=False)

    embed.add_field(name="📊  Polls", value=(
        "`/poll` — Create a reaction poll with 2–10 comma-separated options."
    ), inline=False)

    embed.add_field(name="📌  Pinning", value=(
        "`/pin` — Pin a message in this channel by ID.\n"
        "`/unpin` — Unpin a message in this channel by ID."
    ), inline=False)

    embed.add_field(name="📅  Scheduling", value=(
        "`/schedule` — Schedule a message for a specific date & time (EST). Set `repeat_days` to repeat; `0` = send once.\n"
        "`/schedule-list` — View all scheduled messages for this server.\n"
        "`/schedule-delete` — Delete a scheduled message by its ID."
    ), inline=False)

    embed.add_field(name="🖱️  Right-click (Context Menus)", value=(
        "**Reply as Sumi Bot** — Reply to any message as the bot.\n"
        "**Edit Sumi Bot message** — Edit a bot message with the current content pre-filled.\n"
        "**Delete Sumi Bot message** — Delete a bot message."
    ), inline=False)

    embed.set_footer(text="Most commands require the Manage Messages permission.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- /poll ---
POLL_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

@tree.command(name="poll", description="Create a poll with up to 10 options")
@app_commands.describe(
    question="The poll question",
    options="Comma-separated list of options (2-10)"
)
async def poll(interaction: discord.Interaction, question: str, options: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return

    choices = [o.strip() for o in options.split(",") if o.strip()]
    if len(choices) < 2:
        await interaction.response.send_message("❌ Provide at least 2 options separated by commas.", ephemeral=True)
        return
    if len(choices) > 10:
        await interaction.response.send_message("❌ Maximum 10 options allowed.", ephemeral=True)
        return

    description = "\n".join(f"{POLL_EMOJIS[i]}  {choice}" for i, choice in enumerate(choices))
    embed = discord.Embed(
        title=f"📊  {question}",
        description=description,
        color=discord.Color.blurple(),
    )

    await interaction.response.defer(ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    for i in range(len(choices)):
        await msg.add_reaction(POLL_EMOJIS[i])
    await interaction.delete_original_response()

# --- /pin ---
@tree.command(name="pin", description="Pin a message in this channel")
@app_commands.describe(message_id="ID of the message to pin")
async def pin(interaction: discord.Interaction, message_id: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        await target.pin()
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to pin messages.", ephemeral=True)

# --- /unpin ---
@tree.command(name="unpin", description="Unpin a message in this channel")
@app_commands.describe(message_id="ID of the message to unpin")
async def unpin(interaction: discord.Interaction, message_id: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        await target.unpin()
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unpin messages.", ephemeral=True)

# --- /schedule ---
@tree.command(name="schedule", description="Schedule a message to be sent at a specific date/time (EST)")
@app_commands.describe(
    channel="Channel to send the message in",
    message="Message content to send",
    date="Start date in YYYY-MM-DD format (EST)",
    time="Time in HH:MM 24-hour format (EST)",
    repeat_days="Repeat every N days (0 = send once)",
    image="Image to attach"
)
async def schedule(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    date: str,
    time: str,
    repeat_days: int = 0,
    image: discord.Attachment = None,
):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return

    # Validate date
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await interaction.response.send_message("❌ Invalid date format. Use YYYY-MM-DD.", ephemeral=True)
        return

    # Validate time
    try:
        datetime.strptime(time, "%H:%M")
    except ValueError:
        await interaction.response.send_message("❌ Invalid time format. Use HH:MM (24-hour).", ephemeral=True)
        return

    if repeat_days < 0:
        await interaction.response.send_message("❌ Repeat days cannot be negative.", ephemeral=True)
        return

    next_run = compute_next_run(date, time)
    now = datetime.now(EST)
    if next_run <= now and repeat_days == 0:
        await interaction.response.send_message("❌ That date/time is in the past.", ephemeral=True)
        return
    # If recurring and the first run is in the past, advance to the next future occurrence
    if next_run <= now and repeat_days > 0:
        while next_run <= now:
            next_run += timedelta(days=repeat_days)

    schedules = load_schedules()
    entry = {
        "id": next_schedule_id(schedules),
        "guild_id": interaction.guild_id,
        "channel_id": channel.id,
        "message": message,
        "image_url": image.url if image else None,
        "date": date,
        "time": time,
        "repeat_days": repeat_days,
        "next_run": next_run.isoformat(),
        "creator_id": interaction.user.id,
    }
    schedules.append(entry)
    save_schedules(schedules)

    recurrence_text = f"every {repeat_days} day(s)" if repeat_days > 0 else "once"
    await interaction.response.send_message(
        f"✅ Scheduled (ID **{entry['id']}**): "
        f"<#{channel.id}> — *{message[:50]}{'…' if len(message) > 50 else ''}* "
        f"at **{time} EST** on **{date}**, {recurrence_text}.",
        ephemeral=True,
    )

# --- /schedule-list ---
@tree.command(name="schedule-list", description="View all scheduled messages for this server")
async def schedule_list(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return

    schedules = load_schedules()
    guild_schedules = [s for s in schedules if s["guild_id"] == interaction.guild_id]

    if not guild_schedules:
        await interaction.response.send_message("📭 No scheduled messages for this server.", ephemeral=True)
        return

    lines = []
    for s in guild_schedules:
        recurrence = f"every {s['repeat_days']}d" if s["repeat_days"] > 0 else "once"
        preview = s["message"][:40] + ("…" if len(s["message"]) > 40 else "")
        img_tag = " 🖼️" if s.get("image_url") else ""
        lines.append(
            f"**ID {s['id']}** · <#{s['channel_id']}> · `{s['time']} EST` · "
            f"{recurrence} · next: `{s['next_run'][:16]}`\n> {preview}{img_tag}"
        )

    embed = discord.Embed(
        title="📅 Scheduled Messages",
        description="\n\n".join(lines),
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- /schedule-delete ---
@tree.command(name="schedule-delete", description="Delete a scheduled message by its ID")
@app_commands.describe(schedule_id="The ID of the scheduled message to delete")
async def schedule_delete(interaction: discord.Interaction, schedule_id: int):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return

    schedules = load_schedules()
    entry = next((s for s in schedules if s["id"] == schedule_id and s["guild_id"] == interaction.guild_id), None)
    if not entry:
        await interaction.response.send_message("❌ Schedule not found.", ephemeral=True)
        return

    schedules.remove(entry)
    save_schedules(schedules)
    await interaction.response.send_message(f"✅ Deleted schedule **ID {schedule_id}**.", ephemeral=True)

# --- Background task: check & fire scheduled messages ---
@tasks.loop(seconds=30)
async def schedule_loop():
    now = datetime.now(EST)
    schedules = load_schedules()
    changed = False
    to_remove = []

    for entry in schedules:
        next_run = datetime.fromisoformat(entry["next_run"])
        if now >= next_run:
            channel = bot.get_channel(entry["channel_id"])
            if not channel:
                try:
                    channel = await bot.fetch_channel(entry["channel_id"])
                except Exception:
                    to_remove.append(entry)
                    changed = True
                    continue

            kwargs = {"content": entry["message"]}
            if entry.get("image_url"):
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        async with session.get(entry["image_url"]) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                filename = entry["image_url"].split("/")[-1].split("?")[0]
                                kwargs["file"] = discord.File(fp=__import__("io").BytesIO(data), filename=filename)
                except Exception:
                    pass  # Send without image if download fails

            try:
                await channel.send(**kwargs)
            except Exception:
                pass

            if entry["repeat_days"] > 0:
                # Advance to next future run
                nr = next_run
                while nr <= now:
                    nr += timedelta(days=entry["repeat_days"])
                entry["next_run"] = nr.isoformat()
                changed = True
            else:
                to_remove.append(entry)
                changed = True

    for entry in to_remove:
        schedules.remove(entry)

    if changed:
        save_schedules(schedules)

@schedule_loop.before_loop
async def before_schedule_loop():
    await bot.wait_until_ready()

# ============================================================
# CONTEXT MENU COMMANDS (right-click a message)
# ============================================================

# --- Right-click → Reply as Bot ---
@tree.context_menu(name="Reply as Sumi Bot")
async def context_reply(interaction: discord.Interaction, message: discord.Message):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    class ReplyModal(discord.ui.Modal, title="Reply as Bot"):
        reply_text = discord.ui.TextInput(
            label="Your reply",
            style=discord.TextStyle.paragraph,
            placeholder="Type your reply here...",
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            await message.reply(self.reply_text.value)
            await modal_interaction.response.send_message("_ _", ephemeral=True)
            await modal_interaction.delete_original_response()

    await interaction.response.send_modal(ReplyModal())

# --- Right-click → Edit as Bot ---
@tree.context_menu(name="Edit Sumi Bot message")
async def context_edit(interaction: discord.Interaction, message: discord.Message):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    if message.author != bot.user:
        await interaction.response.send_message("❌ I can only edit my own messages.", ephemeral=True)
        return

    class EditModal(discord.ui.Modal, title="Edit Bot Message"):
        new_content = discord.ui.TextInput(
            label="New content",
            style=discord.TextStyle.paragraph,
            default=message.content,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            await message.edit(content=self.new_content.value)
            await modal_interaction.response.send_message("_ _", ephemeral=True)
            await modal_interaction.delete_original_response()

    await interaction.response.send_modal(EditModal())

# --- Right-click → Delete as Bot ---
@tree.context_menu(name="Delete Sumi Bot message")
async def context_delete(interaction: discord.Interaction, message: discord.Message):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    if message.author != bot.user:
        await interaction.response.send_message("❌ I can only delete my own messages.", ephemeral=True)
        return
    await message.delete()
    await silent(interaction)

# --- Run ---
bot.run(TOKEN)