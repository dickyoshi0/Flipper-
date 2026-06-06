import discord
from discord.ext import commands, tasks
from discord import app_commands, PartialEmoji
import sqlite3
import aiohttp
import os
import re
import asyncio
import io as _io
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, List

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# ---------- Fix SQLite datetime (aware UTC) ----------
def adapt_datetime(dt: datetime) -> str:
    return dt.isoformat()

def convert_datetime(s: bytes) -> datetime:
    dt = datetime.fromisoformat(s.decode())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

DB_PATH = "custom_roles.db"

def get_db():
    return sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)

def init_db():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS guild_config (
        guild_id INTEGER PRIMARY KEY,
        prefix TEXT DEFAULT '!',
        role_add_whitelist TEXT DEFAULT '',
        role_remove_whitelist TEXT DEFAULT '',
        trigger_role_id INTEGER DEFAULT NULL,
        daily_vote_limit INTEGER DEFAULT 1
    )''')
    try:
        c.execute("ALTER TABLE guild_config ADD COLUMN daily_vote_limit INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS custom_roles (
        role_id INTEGER PRIMARY KEY,
        guild_id INTEGER,
        owner_id INTEGER,
        name TEXT,
        color INTEGER,
        icon_url TEXT,
        max_recipients INTEGER DEFAULT 50,
        gradient_colors TEXT DEFAULT NULL,
        stack_count INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS role_memberships (
        user_id INTEGER,
        role_id INTEGER,
        granted_at TIMESTAMP,
        expires_at TIMESTAMP,
        granted_by INTEGER,
        PRIMARY KEY (user_id, role_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER,
        guild_id INTEGER,
        highlighted_role_id INTEGER,
        daily_limit_override INTEGER DEFAULT NULL,
        PRIMARY KEY (user_id, guild_id)
    )''')
    try:
        c.execute("ALTER TABLE user_settings ADD COLUMN daily_limit_override INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS booster_roles (
        role_id INTEGER PRIMARY KEY,
        guild_id INTEGER,
        extra_votes INTEGER DEFAULT 1
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_extra_votes (
        user_id INTEGER,
        guild_id INTEGER,
        extra_votes INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, guild_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_votes (
        user_id INTEGER,
        guild_id INTEGER,
        votes_remaining INTEGER DEFAULT 0,
        last_reset TIMESTAMP,
        PRIMARY KEY (user_id, guild_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vote_log (
        user_id INTEGER,
        role_id INTEGER,
        guild_id INTEGER,
        voted_at TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS gradient_permissions (
        user_id INTEGER,
        guild_id INTEGER,
        PRIMARY KEY (user_id, guild_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS weekly_winners (
        guild_id INTEGER PRIMARY KEY,
        user_id INTEGER,
        notified_week TEXT
    )''')
    try:
        c.execute("ALTER TABLE role_memberships ADD COLUMN warned_expiry INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE lvl_config ADD COLUMN winner_channel_id INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    c.execute('''CREATE TABLE IF NOT EXISTS vc_hub (
        guild_id INTEGER PRIMARY KEY,
        hub_channel_id INTEGER,
        category_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vc_channels (
        channel_id INTEGER PRIMARY KEY,
        guild_id INTEGER,
        owner_id INTEGER,
        is_permanent INTEGER DEFAULT 0,
        has_ownership INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vc_settings (
        user_id INTEGER,
        guild_id INTEGER,
        channel_name TEXT DEFAULT '',
        is_locked INTEGER DEFAULT 0,
        is_hidden INTEGER DEFAULT 0,
        user_limit INTEGER DEFAULT 0,
        status TEXT DEFAULT '',
        saved_perms TEXT DEFAULT '[]',
        has_ownership INTEGER DEFAULT 1,
        PRIMARY KEY (user_id, guild_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vc_permissions (
        channel_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (channel_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vc_deafened (
        channel_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (channel_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vc_muted (
        channel_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (channel_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vc_admin_perms (
        user_id INTEGER,
        guild_id INTEGER,
        perm_type TEXT DEFAULT 'p',
        PRIMARY KEY (user_id, guild_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER,
        guild_id INTEGER,
        role_id INTEGER,
        booster_id INTEGER,
        amount INTEGER DEFAULT 1,
        created_at TIMESTAMP,
        is_read INTEGER DEFAULT 0
    )''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_notif_owner ON notifications(owner_id, guild_id, is_read)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_expires ON role_memberships(expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vote_log_role ON vote_log(role_id, guild_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vote_log_user ON vote_log(user_id, guild_id)")
    conn.commit()
    conn.close()

init_db()

# ---------- Custom Emojis ----------
BTN_BACK = PartialEmoji.from_str("<:back:1506445841953722368>")
BTN_IMAGE = PartialEmoji.from_str("<:image:1506445872857350145>")
BTN_PENCIL = PartialEmoji.from_str("<:pencil:1506445899549769799>")
BTN_COLOR_PENCIL = PartialEmoji.from_str("<:color_pencil:1506445924967120907>")
BTN_LINK = PartialEmoji.from_str("<:link:1506445950699442216>")
BTN_UPLOAD = PartialEmoji.from_str("<:upload:1506445979023446177>")
BTN_EMOJI = PartialEmoji.from_str("<:emoji:1506446009071570994>")
BTN_GRADIENT = PartialEmoji.from_str("<:Gradient:1506488404882231356>")
BTN_TRIGGER = PartialEmoji.from_str("<:Trigger_role:1506533299479380200>")
BTN_PREV = PartialEmoji.from_str("<:previous:1507252351960875048>")
BTN_NEXT = PartialEmoji.from_str("<:next:1507252326140739636>")
BTN_VOTE = "🗳️"
BTN_CANCEL = "❌"

EMOJI_UPLOADING = "<:Uploadingyourimage:1506488562101522603>"
EMOJI_SAVING = "<:savingyourimage:1506488593403875338>"
EMOJI_UPGRADING = "<:upgradingyourrole:1506488625964257290>"
EMOJI_DELETING = "<:deletingyourattachment:1506488656159051857>"

DEFAULT_THUMBNAIL = "<:Lemon:1506451749416865912>"

EMOJI_ADD = "<:add:1506446092261261432>"
EMOJI_DELETE = "<:delete:1506446122401402880>"
EMOJI_USER = "<:user:1506446154429239367>"
EMOJI_STACK = "<:stack:1506446215393575052>"
EMOJI_PERFORMINGARTS = "<:performingarts:1506446244015374356>"
EMOJI_MEMO = "<:memo:1506446282749640704>"
EMOJI_COLOR = "<:color:1506446316488888400>"
EMOJI_HAMMER = "<:hammer_and_wrench:1506446352723345589>"
EMOJI_GEAR = "<:gear:1506446384121909268>"
EMOJI_PIN = "<:pin:1506446456343756840>"
EMOJI_ERROR = "<:error:1506446486995734548>"
EMOJI_SUCCESS = "<:success:1506446515156156476>"
EMOJI_WARNING = "<:warning:1506446542012416020>"
EMOJI_INFO = "<:information_field:1506446568276885535>"
EMOJI_STAR = "<:award:1507252067717218386>"
EMOJI_TRENDING_UP = "<:Up:1509790478470742038>"
EMOJI_TRENDING_DOWN = "<:Down:1509790508879315084>"
EMOJI_TRENDING_FLAT = "<:No:1497117666450870302>"

EMOJI_MOST_USERS = PartialEmoji.from_str("<:Most_users:1507251936041242685>")
EMOJI_EXTRA_BOOST = PartialEmoji.from_str("<:extraboost:1507251980324835439>")
EMOJI_ROLE_RANKS = PartialEmoji.from_str("<:Roleranks:1507252021739130921>")
EMOJI_MEMBERS = PartialEmoji.from_str("<:Members:1507252110792851496>")
EMOJI_BOOSTED_COUNT = PartialEmoji.from_str("<:Boosted_count:1507252148793245828>")
EMOJI_CALENDAR = PartialEmoji.from_str("<:calender:1507252185761710091>")
EMOJI_BOOSTED = PartialEmoji.from_str("<:Boosted:1507252224575799436>")
EMOJI_DAILY = PartialEmoji.from_str("<:daily:1507252290023850034>")

# ---------- Helper Functions ----------
def hex_to_int(hex_color: str) -> int:
    hex_color = hex_color.lstrip('#').strip()
    if len(hex_color) == 6 and all(c in '0123456789ABCDEFabcdef' for c in hex_color):
        return int(hex_color, 16)
    raise ValueError("Invalid hex color")

def int_to_hex(color_int: int) -> str:
    return f"#{color_int:06x}"

def can_use_gradient(guild: discord.Guild) -> bool:
    return guild.premium_tier >= 3

async def get_or_fetch_member(guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
    member = guild.get_member(user_id)
    if not member:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
    return member

def emoji_to_url(emoji_input: str) -> Optional[str]:
    if emoji_input.isdigit():
        return f"https://cdn.discordapp.com/emojis/{emoji_input}.png"
    match = re.match(r"<a?:(\w+):(\d+)>", emoji_input)
    if match:
        emoji_id = match.group(2)
        animated = match.group(0).startswith("<a:")
        ext = "gif" if animated else "png"
        return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
    return None

async def ensure_role_highlighted(role: discord.Role, guild: discord.Guild):
    bot_member = guild.me
    if bot_member is None:
        return
    bot_top_role = bot_member.top_role
    target_position = bot_top_role.position - 1
    if target_position < 0:
        target_position = 0
    if role.position < target_position:
        try:
            await role.edit(position=target_position)
        except:
            pass

async def get_highlighted_role(user_id: int, guild_id: int) -> Optional[int]:
    with get_db() as conn:
        cur = conn.execute("SELECT highlighted_role_id FROM user_settings WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = cur.fetchone()
        return row[0] if row else None

async def set_highlighted_role(member: discord.Member, role_id: Optional[int]):
    with get_db() as conn:
        if role_id is None:
            conn.execute("DELETE FROM user_settings WHERE user_id = ? AND guild_id = ?", (member.id, member.guild.id))
        else:
            conn.execute("INSERT OR REPLACE INTO user_settings (user_id, guild_id, highlighted_role_id) VALUES (?, ?, ?)",
                         (member.id, member.guild.id, role_id))
        conn.commit()
    
    if role_id:
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            bot_member = member.guild.me
            bot_highest_role = bot_member.top_role
            if role.position >= bot_highest_role.position:
                return False
            user_roles = [r for r in member.roles if r.name != "@everyone"]
            if not user_roles:
                return False
            highest_user_role = max(user_roles, key=lambda r: r.position)
            new_position = highest_user_role.position + 1
            if new_position >= bot_highest_role.position:
                new_position = bot_highest_role.position - 1
            if new_position < 0:
                new_position = 0
            try:
                await role.edit(position=new_position)
                return True
            except:
                return False
    return True

# ---------- Trigger Role Helpers ----------
async def grant_custom_role_to_existing_members(guild: discord.Guild, trigger_role_id: int):
    trigger_role = guild.get_role(trigger_role_id)
    if not trigger_role:
        return
    bot_member = guild.me
    if not bot_member:
        return
    for member in guild.members:
        if trigger_role in member.roles:
            existing = await get_user_role_membership(member.id, guild.id)
            if not existing:
                await create_custom_role_for_user(member, guild, bot_member)
            await asyncio.sleep(0.5)

async def get_trigger_role_id(guild_id: int) -> Optional[int]:
    with get_db() as conn:
        cur = conn.execute("SELECT trigger_role_id FROM guild_config WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
        return row[0] if row else None

async def set_trigger_role_id(guild_id: int, role_id: Optional[int], guild: discord.Guild = None):
    with get_db() as conn:
        conn.execute("UPDATE guild_config SET trigger_role_id = ? WHERE guild_id = ?", (role_id, guild_id))
        conn.commit()
    if role_id is not None and guild:
        await grant_custom_role_to_existing_members(guild, role_id)

async def create_custom_role_for_user(member: discord.Member, guild: discord.Guild, author: discord.Member):
    existing = await get_user_role_membership(member.id, guild.id)
    if existing:
        return
    role_name = f"Custom-{member.name}"
    try:
        new_role = await guild.create_role(name=role_name, color=discord.Color(0x99aab5), reason="Auto-created from trigger role")
    except discord.Forbidden:
        return
    default_icon_url = emoji_to_url(DEFAULT_THUMBNAIL)
    with get_db() as conn:
        conn.execute("INSERT INTO custom_roles (role_id, guild_id, owner_id, name, color, icon_url, max_recipients, stack_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (new_role.id, guild.id, member.id, role_name, 0x99aab5, default_icon_url, 50, 0))
        granted_at = datetime.now(timezone.utc)
        expires_at = granted_at + timedelta(days=30)
        conn.execute("INSERT INTO role_memberships (user_id, role_id, granted_at, expires_at, granted_by) VALUES (?, ?, ?, ?, ?)",
                     (member.id, new_role.id, granted_at, expires_at, author.id))
        conn.commit()
    await member.add_roles(new_role)
    await ensure_role_highlighted(new_role, guild)

async def get_all_custom_roles(guild_id: int) -> List[Tuple[int, str, int, str]]:
    with get_db() as conn:
        cur = conn.execute("SELECT role_id, name, owner_id, icon_url FROM custom_roles WHERE guild_id = ?", (guild_id,))
        return cur.fetchall()

# ---------- Voting / Boost Helpers ----------
async def get_daily_vote_limit(guild_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute("SELECT daily_vote_limit FROM guild_config WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
        if row:
            return row[0]
        else:
            conn.execute("INSERT INTO guild_config (guild_id, daily_vote_limit) VALUES (?, 1)", (guild_id,))
            conn.commit()
            return 1

async def set_daily_vote_limit(guild_id: int, limit: int):
    with get_db() as conn:
        conn.execute("UPDATE guild_config SET daily_vote_limit = ? WHERE guild_id = ?", (limit, guild_id))
        conn.commit()

async def get_user_daily_limit_override(user_id: int, guild_id: int) -> Optional[int]:
    with get_db() as conn:
        cur = conn.execute("SELECT daily_limit_override FROM user_settings WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = cur.fetchone()
        return row[0] if row else None

async def set_user_daily_limit_override(user_id: int, guild_id: int, limit: Optional[int]):
    with get_db() as conn:
        if limit is None:
            conn.execute("UPDATE user_settings SET daily_limit_override = NULL WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        else:
            conn.execute("INSERT OR REPLACE INTO user_settings (user_id, guild_id, daily_limit_override) VALUES (?, ?, ?)", (user_id, guild_id, limit))
        conn.commit()

async def get_user_effective_daily_limit(user_id: int, guild_id: int) -> int:
    override = await get_user_daily_limit_override(user_id, guild_id)
    if override is not None:
        return override
    return await get_daily_vote_limit(guild_id)

async def get_booster_roles(guild_id: int) -> List[Tuple[int, int]]:
    with get_db() as conn:
        cur = conn.execute("SELECT role_id, extra_votes FROM booster_roles WHERE guild_id = ?", (guild_id,))
        return cur.fetchall()

async def add_booster_role(guild_id: int, role_id: int, extra_votes: int):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO booster_roles (role_id, guild_id, extra_votes) VALUES (?, ?, ?)",
                     (role_id, guild_id, extra_votes))
        conn.commit()

async def remove_booster_role(guild_id: int, role_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM booster_roles WHERE role_id = ? AND guild_id = ?", (role_id, guild_id))
        conn.commit()

async def get_user_extra_votes(user_id: int, guild_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute("SELECT extra_votes FROM user_extra_votes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = cur.fetchone()
        return row[0] if row else 0

async def set_user_extra_votes(user_id: int, guild_id: int, extra: int):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_extra_votes (user_id, guild_id, extra_votes) VALUES (?, ?, ?)",
                     (user_id, guild_id, extra))
        conn.commit()

async def add_user_extra_votes(user_id: int, guild_id: int, amount: int):
    current = await get_user_extra_votes(user_id, guild_id)
    await set_user_extra_votes(user_id, guild_id, current + amount)

async def get_user_total_votes(user: discord.Member, guild_id: int) -> int:
    base = await get_user_effective_daily_limit(user.id, guild_id)
    extra_from_roles = 0
    booster_roles = await get_booster_roles(guild_id)
    for role_id, extra_votes in booster_roles:
        if user.get_role(role_id):
            extra_from_roles += extra_votes
    return base + extra_from_roles

async def get_daily_votes_remaining(user_id: int, guild_id: int) -> int:
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        cur = conn.execute("SELECT votes_remaining, last_reset FROM user_votes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = cur.fetchone()
        if not row:
            return -1
        votes_remaining, last_reset = row
        if votes_remaining is None:
            return -1
        if last_reset.tzinfo is None:
            last_reset = last_reset.replace(tzinfo=timezone.utc)
        if now - last_reset > timedelta(hours=12):
            conn.execute("DELETE FROM user_votes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            conn.commit()
            return -1
        return votes_remaining

async def reset_daily_votes(user_id: int, guild_id: int, total: int):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_votes (user_id, guild_id, votes_remaining, last_reset) VALUES (?, ?, ?, ?)",
                     (user_id, guild_id, total, datetime.now(timezone.utc)))
        conn.commit()

async def use_vote(user: discord.Member, guild_id: int, amount: int = 1) -> Tuple[bool, int, int]:
    daily_rem = await get_daily_votes_remaining(user.id, guild_id)
    if daily_rem == -1:
        total_daily = await get_user_total_votes(user, guild_id)
        await reset_daily_votes(user.id, guild_id, total_daily)
        daily_rem = total_daily
    extra_rem = await get_user_extra_votes(user.id, guild_id)
    
    total_available = daily_rem + extra_rem
    if total_available < amount:
        return False, 0, 0
    
    daily_used = min(daily_rem, amount)
    extra_used = amount - daily_used
    
    if daily_used > 0:
        with get_db() as conn:
            conn.execute("UPDATE user_votes SET votes_remaining = votes_remaining - ? WHERE user_id = ? AND guild_id = ?",
                         (daily_used, user.id, guild_id))
            conn.commit()
    if extra_used > 0:
        new_extra = extra_rem - extra_used
        await set_user_extra_votes(user.id, guild_id, new_extra)
    
    return True, daily_used, extra_used

async def add_vote_to_role(role_id: int, guild_id: int, user_id: int, amount: int = 1):
    with get_db() as conn:
        for _ in range(amount):
            conn.execute("INSERT INTO vote_log (user_id, role_id, guild_id, voted_at) VALUES (?, ?, ?, ?)",
                         (user_id, role_id, guild_id, datetime.now(timezone.utc)))
        conn.commit()

async def get_total_votes_on_role(role_id: int, guild_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM vote_log WHERE role_id = ? AND guild_id = ?",
            (role_id, guild_id)
        )
        return cur.fetchone()[0]

async def remove_any_votes_from_role(role_id: int, guild_id: int, amount: int) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT rowid FROM vote_log WHERE role_id = ? AND guild_id = ? LIMIT ?",
            (role_id, guild_id, amount)
        )
        rowids = [row[0] for row in cur.fetchall()]
        if rowids:
            conn.execute(f"DELETE FROM vote_log WHERE rowid IN ({','.join('?' * len(rowids))})", rowids)
            conn.commit()
        return len(rowids)

# ---------- Notification Helpers ----------
async def create_boost_notification(owner_id: int, guild_id: int, role_id: int, booster_id: int, amount: int):
    if owner_id == booster_id:
        return
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notifications (owner_id, guild_id, role_id, booster_id, amount, created_at, is_read) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (owner_id, guild_id, role_id, booster_id, amount, datetime.now(timezone.utc))
        )
        conn.commit()

async def get_unread_notification_count(owner_id: int, guild_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE owner_id = ? AND guild_id = ? AND is_read = 0",
            (owner_id, guild_id)
        )
        return cur.fetchone()[0]

async def get_unread_notifications_grouped(owner_id: int, guild_id: int) -> list:
    with get_db() as conn:
        cur = conn.execute(
            """SELECT booster_id, SUM(amount) as total, MAX(created_at) as latest
               FROM notifications
               WHERE owner_id = ? AND guild_id = ? AND is_read = 0
               GROUP BY booster_id
               ORDER BY latest DESC""",
            (owner_id, guild_id)
        )
        return cur.fetchall()

async def mark_notifications_read(owner_id: int, guild_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE owner_id = ? AND guild_id = ?",
            (owner_id, guild_id)
        )
        conn.commit()

async def get_weekly_votes(guild_id: int) -> Dict[int, int]:
    now = datetime.now(timezone.utc)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    with get_db() as conn:
        cur = conn.execute("""
            SELECT role_id, COUNT(*) FROM vote_log
            WHERE guild_id = ? AND voted_at >= ?
            GROUP BY role_id
        """, (guild_id, start_of_week))
        return {row[0]: row[1] for row in cur.fetchall()}

async def get_last_week_votes(guild_id: int) -> Dict[int, int]:
    now = datetime.now(timezone.utc)
    start_of_last_week = now - timedelta(days=now.weekday() + 7)
    start_of_last_week = start_of_last_week.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_last_week = start_of_last_week + timedelta(days=7)
    with get_db() as conn:
        cur = conn.execute("""
            SELECT role_id, COUNT(*) FROM vote_log
            WHERE guild_id = ? AND voted_at >= ? AND voted_at < ?
            GROUP BY role_id
        """, (guild_id, start_of_last_week, end_of_last_week))
        return {row[0]: row[1] for row in cur.fetchall()}

async def get_role_member_count(role_id: int, guild_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM role_memberships WHERE role_id = ?", (role_id,))
        return cur.fetchone()[0]

async def get_role_members(role_id: int) -> List[Tuple[int, datetime]]:
    with get_db() as conn:
        cur = conn.execute("SELECT user_id, granted_at FROM role_memberships WHERE role_id = ?", (role_id,))
        return cur.fetchall()

async def get_user_votes_for_role(user_id: int, role_id: int, guild_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM vote_log WHERE user_id = ? AND role_id = ? AND guild_id = ?", (user_id, role_id, guild_id))
        return cur.fetchone()[0]

# ---------- Gradient Permission Helpers ----------
async def has_gradient_permission(user_id: int, guild_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("SELECT 1 FROM gradient_permissions WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        return cur.fetchone() is not None

async def grant_gradient_permission(user_id: int, guild_id: int):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO gradient_permissions (user_id, guild_id) VALUES (?, ?)", (user_id, guild_id))
        conn.commit()

async def revoke_gradient_permission(user_id: int, guild_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM gradient_permissions WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        conn.commit()


def build_winner_embed(user: discord.Member, next_reset_ts: int) -> discord.Embed:
    embed = discord.Embed(
        description=(
            "For being the most boosted user this week, they can now customize their **__role__** "
            "with **gradient** or **holographic** colors"
        ),
        color=0xFFD700
    )
    embed.set_author(name="Congratulations", icon_url=user.avatar.url if user.avatar else None)
    embed.add_field(
        name="<:calender:1511143858476421171>  Next Reset",
        value=f"<t:{next_reset_ts}:R>",
        inline=False
    )
    embed.add_field(
        name="<a:daily_perk:1510988210023436348>  Reward",
        value="Gradient / Holographic Role Color",
        inline=False
    )
    embed.add_field(
        name="<:king:1497380314295832616>",
        value="<:extend_end:1511143598664712343>  Discover the rankings with **`!role overview`**",
        inline=False
    )
    return embed


async def announce_weekly_winner(guild: discord.Guild, bot):
    try:
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        with get_db() as conn:
            already = conn.execute(
                "SELECT notified_week FROM weekly_winners WHERE guild_id = ?", (guild.id,)
            ).fetchone()
        if already and already[0] == week_start:
            return
        last_week = await get_last_week_votes(guild.id)
        if not last_week:
            return
        max_votes = max(last_week.values())
        if max_votes == 0:
            return
        top_roles = [rid for rid, v in last_week.items() if v == max_votes]
        if len(top_roles) != 1:
            return
        role_id = top_roles[0]
        with get_db() as conn:
            row = conn.execute("SELECT owner_id FROM custom_roles WHERE role_id = ?", (role_id,)).fetchone()
        if not row:
            return
        new_winner_id = row[0]
        with get_db() as conn:
            prev = conn.execute("SELECT user_id FROM weekly_winners WHERE guild_id = ?", (guild.id,)).fetchone()
        if prev and prev[0] != new_winner_id:
            await revoke_gradient_permission(prev[0], guild.id)
        await grant_gradient_permission(new_winner_id, guild.id)
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO weekly_winners (guild_id, user_id, notified_week) VALUES (?,?,?)",
                (guild.id, new_winner_id, week_start)
            )
            conn.commit()
        next_reset_ts = int((now + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        try:
            winner_member = guild.get_member(new_winner_id) or await guild.fetch_member(new_winner_id)
        except Exception:
            return
        if not winner_member:
            return
        embed = build_winner_embed(winner_member, next_reset_ts)
        cfg = get_lvl_config(guild.id)
        channel = None
        if cfg.get("winner_channel_id"):
            channel = guild.get_channel(cfg["winner_channel_id"])
        if not channel and cfg.get("lvlup_channel_ids"):
            for cid in cfg["lvlup_channel_ids"].split(","):
                cid = cid.strip()
                if cid.isdigit():
                    ch = guild.get_channel(int(cid))
                    if ch:
                        channel = ch
                        break
        if channel:
            await channel.send(content=winner_member.mention, embed=embed)
        else:
            await try_dm(winner_member, embed)
    except Exception as e:
        print(f"[weekly winner] Error for {guild.name}: {e}")


async def get_weekly_top_role_owner(guild_id: int) -> Optional[int]:
    weekly = await get_weekly_votes(guild_id)
    if not weekly:
        return None
    max_votes = max(weekly.values())
    top_roles = [role_id for role_id, votes in weekly.items() if votes == max_votes]
    if len(top_roles) != 1:
        return None
    role_id = top_roles[0]
    with get_db() as conn:
        cur = conn.execute("SELECT owner_id FROM custom_roles WHERE role_id = ?", (role_id,))
        row = cur.fetchone()
        return row[0] if row else None

async def can_user_use_gradient(user: discord.Member, guild: discord.Guild) -> bool:
    if not can_use_gradient(guild):
        return False
    if user.guild_permissions.administrator:
        return True
    if await has_gradient_permission(user.id, guild.id):
        return True
    top_owner = await get_weekly_top_role_owner(guild.id)
    if top_owner == user.id:
        return True
    return False

# ---------- Send & Delete Helper ----------
async def try_dm(user: discord.User, embed: discord.Embed):
    try:
        await user.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def send_then_delete(ctx_or_inter, embed: discord.Embed, delay: int = 2):
    if isinstance(ctx_or_inter, discord.Interaction):
        try:
            if not ctx_or_inter.response.is_done():
                await ctx_or_inter.response.defer()
                msg = await ctx_or_inter.followup.send(embed=embed, wait=True)
            else:
                msg = await ctx_or_inter.followup.send(embed=embed, wait=True)
        except discord.InteractionResponded:
            msg = await ctx_or_inter.followup.send(embed=embed, wait=True)
    else:
        msg = await ctx_or_inter.send(embed=embed)
    async def delete():
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except:
            pass
    asyncio.create_task(delete())

# ---------- File Upload Listener ----------
upload_listeners: Dict[int, asyncio.Future] = {}

# ---------- Gradient Helper ----------
async def _apply_gradient_to_role(role: discord.Role, color1: int, color2: int) -> None:
    """Apply two gradient colors to a Discord role via the REST API colors[] field."""
    token = role._state.http.token
    url = f"https://discord.com/api/v10/guilds/{role.guild.id}/roles/{role.id}"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    payload = {"colors": [color1, color2]}
    async with aiohttp.ClientSession() as session:
        async with session.patch(url, json=payload, headers=headers) as resp:
            if resp.status not in (200, 204):
                body = await resp.text()
                raise Exception(f"Discord API {resp.status}: {body}")

# ---------- Icon Image Helpers ----------
def _process_icon_bytes(data: bytes) -> bytes:
    """Auto-resize and compress image for Discord role icons (max 256x256, max 256KB)."""
    if not _PIL_AVAILABLE:
        return data
    try:
        img = _PILImage.open(_io.BytesIO(data)).convert("RGBA")
        
        # Step 1: Resize to max 256x256 (maintains aspect ratio)
        img.thumbnail((256, 256), _PILImage.LANCZOS)
        
        # Step 2: Save as PNG to buffer
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        size_kb = buf.getbuffer().nbytes / 1024
        
        # Step 3: If still >256KB, compress
        if buf.getbuffer().nbytes > 256 * 1024:
            # Try PNG optimize first
            buf = _io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            
            # If still too large, reduce to 128x128
            if buf.getbuffer().nbytes > 256 * 1024:
                img.thumbnail((128, 128), _PILImage.LANCZOS)
                buf = _io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                
                # If STILL too large, reduce to 64x64 (last resort)
                if buf.getbuffer().nbytes > 256 * 1024:
                    img.thumbnail((64, 64), _PILImage.LANCZOS)
                    buf = _io.BytesIO()
                    img.save(buf, format="PNG", optimize=True)
        
        # Step 4: Final check – if still over 256KB, log warning but return anyway
        final_size_kb = buf.getbuffer().nbytes / 1024
        if final_size_kb > 256:
            print(f"[WARN] Role icon still {final_size_kb:.1f}KB after compression (Discord limit 256KB)")
        
        return buf.getvalue()
        
    except Exception as e:
        print(f"[ERROR] Failed to process image: {e}")
        return data

# ---------- Gradient Modal ----------
class GradientModal(discord.ui.Modal):
    def __init__(self, role: discord.Role, role_id: int, guild: discord.Guild, original_message: discord.Message):
        super().__init__(title="Set Gradient Colors")
        self.role = role
        self.role_id = role_id
        self.guild = guild
        self.original_message = original_message
        self.color1 = discord.ui.TextInput(label="First Color", placeholder="#ff0000 or ff0000", required=True)
        self.color2 = discord.ui.TextInput(label="Second Color", placeholder="#0000ff or 0000ff", required=True)
        self.add_item(self.color1)
        self.add_item(self.color2)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color1_int = hex_to_int(self.color1.value)
            color2_int = hex_to_int(self.color2.value)
            with get_db() as conn:
                conn.execute("UPDATE custom_roles SET gradient_colors = ? WHERE role_id = ?", (f"{color1_int},{color2_int}", self.role_id))
                conn.commit()
            color_note = ""
            try:
                await _apply_gradient_to_role(self.role, color1_int, color2_int)
            except Exception as ce:
                color_note = f"\n{EMOJI_WARNING} *Could not apply gradient to role — check bot permissions and role hierarchy: {ce}*"
            embed = discord.Embed(
                description=(
                    f"{EMOJI_SUCCESS} **Gradient colors applied!**\n"
                    f"Color 1: `{int_to_hex(color1_int)}` · Color 2: `{int_to_hex(color2_int)}`{color_note}"
                ),
                color=discord.Color(color1_int)
            )
            await interaction.response.send_message(embed=embed)
            await update_role_info_display(self.original_message, self.role, self.role_id)
        except ValueError:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid hex color format.** Use `#ff0000` or `ff0000`.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

# ---------- Modals for Name, Color, Icon ----------
class RoleNameModal(discord.ui.Modal):
    def __init__(self, role: discord.Role, role_id: int, original_message: discord.Message):
        super().__init__(title="Change Role Name")
        self.role = role
        self.role_id = role_id
        self.original_message = original_message
        self.name_input = discord.ui.TextInput(label="New Name", placeholder="Enter new role name", max_length=100)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name_input.value
        await self.role.edit(name=new_name)
        with get_db() as conn:
            conn.execute("UPDATE custom_roles SET name = ? WHERE role_id = ?", (new_name, self.role_id))
            conn.commit()
        await ensure_role_highlighted(self.role, interaction.guild)
        embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Role name changed to {new_name}**", color=discord.Color.green())
        await send_then_delete(interaction, embed)
        await update_role_info_display(self.original_message, self.role, self.role_id)

class RoleColorModal(discord.ui.Modal):
    def __init__(self, role: discord.Role, role_id: int, original_message: discord.Message):
        super().__init__(title="Change Role Color")
        self.role = role
        self.role_id = role_id
        self.original_message = original_message
        self.color_input = discord.ui.TextInput(label="Hex Color", placeholder="#ff0000 or ff0000")
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color_int = hex_to_int(self.color_input.value)
            await self.role.edit(color=discord.Color(color_int))
            with get_db() as conn:
                conn.execute("UPDATE custom_roles SET color = ? WHERE role_id = ?", (color_int, self.role_id))
                conn.commit()
            await ensure_role_highlighted(self.role, interaction.guild)
            embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Role color changed to {int_to_hex(color_int)}**", color=discord.Color(color_int))
            await send_then_delete(interaction, embed)
            await update_role_info_display(self.original_message, self.role, self.role_id)
        except ValueError:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid hex color.** Use format like `#ff0000` or `ff0000`.", color=discord.Color.red())
            await send_then_delete(interaction, embed)

class IconURLModal(discord.ui.Modal):
    def __init__(self, role: discord.Role, role_id: int, original_message: discord.Message):
        super().__init__(title="Set Role Icon from URL")
        self.role = role
        self.role_id = role_id
        self.original_message = original_message
        self.url_input = discord.ui.TextInput(label="Image URL", placeholder="https://example.com/image.png")
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url_input.value
        with get_db() as conn:
            conn.execute("UPDATE custom_roles SET icon_url = ? WHERE role_id = ?", (url, self.role_id))
            conn.commit()
        icon_error = ""
        if interaction.guild.premium_tier < 2:
            icon_error = f"\n{EMOJI_WARNING} *Role icon display requires **Boost Level 2**. Icon saved but not yet applied to the role.*"
        else:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200 and resp.content_type.startswith('image/'):
                            img_data = _process_icon_bytes(await resp.read())
                            await self.role.edit(icon=img_data)
                        else:
                            icon_error = f"\n{EMOJI_WARNING} *Could not download image from that URL (HTTP {resp.status}). Make sure the link points directly to an image file.*"
            except Exception as e:
                icon_error = f"\n{_icon_error_msg(e)}"
        await ensure_role_highlighted(self.role, interaction.guild)
        embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Your role icon has been saved**{icon_error}", color=discord.Color.green())
        await send_then_delete(interaction, embed)
        await update_role_info_display(self.original_message, self.role, self.role_id)

class IconEmojiModal(discord.ui.Modal):
    def __init__(self, role: discord.Role, role_id: int, original_message: discord.Message):
        super().__init__(title="Set Role Icon from Emoji")
        self.role = role
        self.role_id = role_id
        self.original_message = original_message
        self.emoji_input = discord.ui.TextInput(label="Custom Emoji", placeholder="Emoji ID or <:name:123456789>", max_length=100)
        self.add_item(self.emoji_input)

    async def on_submit(self, interaction: discord.Interaction):
        emoji_str = self.emoji_input.value
        url = emoji_to_url(emoji_str)
        if not url:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Could not recognise the emoji.**\nOnly **custom emojis** (with an ID) can be used as role icons.", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        with get_db() as conn:
            conn.execute("UPDATE custom_roles SET icon_url = ? WHERE role_id = ?", (url, self.role_id))
            conn.commit()
        icon_error = ""
        if interaction.guild.premium_tier < 2:
            icon_error = f"\n{EMOJI_WARNING} *Role icon display requires **Boost Level 2**. Icon saved but not yet applied to the role.*"
        else:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200 and resp.content_type.startswith('image/'):
                            img_data = _process_icon_bytes(await resp.read())
                            await self.role.edit(icon=img_data)
                        else:
                            icon_error = f"\n{EMOJI_WARNING} *Could not download emoji image (HTTP {resp.status}).*"
            except Exception as e:
                icon_error = f"\n{_icon_error_msg(e)}"
        await ensure_role_highlighted(self.role, interaction.guild)
        embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Your role icon has been saved**{icon_error}", color=discord.Color.green())
        await send_then_delete(interaction, embed)
        await update_role_info_display(self.original_message, self.role, self.role_id)

# ---------- Upload Views (original timing) ----------
# ---------- Timeout Mixin ----------
class DisableOnTimeoutView(discord.ui.View):
    """Disables all buttons/selects when the view times out."""
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class IconUploadView(DisableOnTimeoutView):
    def __init__(self, role: discord.Role, role_id: int, user_id: int, original_message: discord.Message):
        super().__init__(timeout=60)
        self.role = role
        self.role_id = role_id
        self.user_id = user_id
        self.original_message = original_message
        self.user_message = None

    async def on_timeout(self):
        upload_listeners.pop(self.user_id, None)

    async def start_upload(self, interaction: discord.Interaction):
        self.clear_items()
        cancel_btn = discord.ui.Button(emoji=BTN_CANCEL, label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)
        # Defer so we can edit original_message freely in perform_upload
        await interaction.response.defer()
        await self.perform_upload(interaction)

    async def perform_upload(self, interaction: discord.Interaction):
        status_embed = discord.Embed(title=f"{BTN_UPLOAD}", description=f"{EMOJI_UPLOADING} **Send an image in 60 seconds**\n\nThe image will be set as your role icon.", color=discord.Color.blue())
        status_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        status_embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/749463659999395891.png")
        await self.original_message.edit(embed=status_embed, view=self)

        future = asyncio.get_event_loop().create_future()
        upload_listeners[self.user_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=60.0)
            if isinstance(result, discord.Message):
                self.user_message = result
                attachment_url = result.attachments[0].url
            else:
                attachment_url = result

            status_embed.description = f"{EMOJI_UPLOADING} **Uploading...**"
            await self.original_message.edit(embed=status_embed)
            await asyncio.sleep(2)

            status_embed.description = f"{EMOJI_SAVING} **Saving...**"
            await self.original_message.edit(embed=status_embed)
            with get_db() as conn:
                conn.execute("UPDATE custom_roles SET icon_url = ? WHERE role_id = ?", (attachment_url, self.role_id))
                conn.commit()
            await asyncio.sleep(2)

            status_embed.description = f"{EMOJI_UPGRADING} **Upgrading role...**"
            await self.original_message.edit(embed=status_embed)
            icon_error = ""
            if interaction.guild.premium_tier < 2:
                icon_error = f"\n{EMOJI_WARNING} *Role icon display requires **Boost Level 2**. Icon saved but not yet applied to the role.*"
            else:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(attachment_url) as resp:
                            if resp.status == 200 and resp.content_type.startswith('image/'):
                                img_data = _process_icon_bytes(await resp.read())
                                await self.role.edit(icon=img_data)
                            else:
                                icon_error = f"\n{EMOJI_WARNING} *Could not process the uploaded image (HTTP {resp.status}). Please upload a PNG, JPG, or WebP file.*"
                except Exception as e:
                    icon_error = f"\n{_icon_error_msg(e)}"
            await ensure_role_highlighted(self.role, interaction.guild)

            if self.user_message:
                status_embed.description = f"{EMOJI_DELETING} **Cleaning up...**"
                await self.original_message.edit(embed=status_embed)
                async def delete_later():
                    await asyncio.sleep(2)
                    try:
                        await self.user_message.delete()
                    except:
                        pass
                asyncio.create_task(delete_later())

            await update_role_info_display(self.original_message, self.role, self.role_id)
            success_embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Role icon successfully saved!**{icon_error}", color=discord.Color.green())
            success_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await send_then_delete(interaction, success_embed)

        except asyncio.TimeoutError:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Upload timed out. Please try again.**", color=discord.Color.red())
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await interaction.followup.send(embed=embed)
            await update_role_info_display(self.original_message, self.role, self.role_id)
        finally:
            upload_listeners.pop(self.user_id, None)

    async def cancel_callback(self, interaction: discord.Interaction):
        future = upload_listeners.pop(self.user_id, None)
        if future and not future.done():
            future.cancel()
        await update_role_info_display(self.original_message, self.role, self.role_id)
        await interaction.response.defer()

    @discord.ui.button(emoji=BTN_UPLOAD, label="", style=discord.ButtonStyle.green)
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_upload(interaction)

    @discord.ui.button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.primary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        gradient_allowed = await can_user_use_gradient(interaction.user, interaction.guild)
        embed = discord.Embed(
            title=f"{EMOJI_HAMMER} **Role Editing**",
            description="Choose what you'd like to change.",
            color=self.role.color
        )
        view = RoleEditView(self.role, self.role_id, self.user_id, self.role.guild, self.original_message, gradient_allowed=gradient_allowed)
        await self.original_message.edit(embed=embed, view=view)

class IconSelectionView(DisableOnTimeoutView):
    def __init__(self, role: discord.Role, role_id: int, user_id: int, original_message: discord.Message):
        super().__init__(timeout=60)
        self.role = role
        self.role_id = role_id
        self.user_id = user_id
        self.original_message = original_message

    @discord.ui.button(emoji=BTN_UPLOAD, label="", style=discord.ButtonStyle.green)
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = discord.Embed(title=f"{BTN_UPLOAD}", description=f"{EMOJI_UPLOADING} **Click the button below to start the upload.**", color=discord.Color.blue())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/749463659999395891.png")
        view = IconUploadView(self.role, self.role_id, self.user_id, self.original_message)
        await self.original_message.edit(embed=embed, view=view)

    @discord.ui.button(emoji=BTN_LINK, label="URL", style=discord.ButtonStyle.primary)
    async def url_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = IconURLModal(self.role, self.role_id, self.original_message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(emoji=BTN_EMOJI, label="Emoji", style=discord.ButtonStyle.primary)
    async def emoji_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = IconEmojiModal(self.role, self.role_id, self.original_message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        gradient_allowed = await can_user_use_gradient(interaction.user, interaction.guild)
        embed = discord.Embed(
            title=f"{EMOJI_HAMMER} **Role Editing**",
            description="Choose what you'd like to change.",
            color=self.role.color
        )
        view = RoleEditView(self.role, self.role_id, self.user_id, self.role.guild, self.original_message, gradient_allowed=gradient_allowed)
        await self.original_message.edit(embed=embed, view=view)

class RoleEditView(DisableOnTimeoutView):
    def __init__(self, role: discord.Role, role_id: int, user_id: int, guild: discord.Guild, original_message: discord.Message, show_gradient: bool = True, gradient_allowed: bool = False):
        super().__init__(timeout=120)
        self.role = role
        self.role_id = role_id
        self.user_id = user_id
        self.guild = guild
        self.original_message = original_message

        self.add_item(discord.ui.Button(emoji=BTN_PENCIL, label="Name", style=discord.ButtonStyle.primary, custom_id="name_btn"))
        self.add_item(discord.ui.Button(emoji=BTN_COLOR_PENCIL, label="Color", style=discord.ButtonStyle.primary, custom_id="color_btn"))
        self.add_item(discord.ui.Button(emoji=BTN_IMAGE, label="Icon", style=discord.ButtonStyle.primary, custom_id="icon_btn"))
        self.add_item(discord.ui.Button(emoji=BTN_GRADIENT, label="Enhance Color", style=discord.ButtonStyle.secondary, custom_id="gradient_btn", disabled=not gradient_allowed))
        self.add_item(discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary, custom_id="back_btn"))

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "name_btn":
                    child.callback = self.name_button
                elif child.custom_id == "color_btn":
                    child.callback = self.color_button
                elif child.custom_id == "icon_btn":
                    child.callback = self.icon_button
                elif child.custom_id == "gradient_btn":
                    child.callback = self.role_style_color_callback
                elif child.custom_id == "back_btn":
                    child.callback = self.back_button

    def _is_authorized(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id or interaction.user.guild_permissions.administrator

    async def name_button(self, interaction: discord.Interaction):
        if not self._is_authorized(interaction):
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Only the role owner can edit this role.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        modal = RoleNameModal(self.role, self.role_id, self.original_message)
        await interaction.response.send_modal(modal)

    async def color_button(self, interaction: discord.Interaction):
        if not self._is_authorized(interaction):
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Only the role owner can edit this role.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        modal = RoleColorModal(self.role, self.role_id, self.original_message)
        await interaction.response.send_modal(modal)

    async def icon_button(self, interaction: discord.Interaction):
        if not self._is_authorized(interaction):
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Only the role owner can edit this role.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        await interaction.response.defer()
        guild = interaction.guild
        issues = []

        if not guild.me.guild_permissions.manage_roles:
            issues.append(f"{EMOJI_ERROR} **Bot is missing `Manage Roles` permission.**\nGrant it in Server Settings → Roles → Bot.")

        if guild.me.top_role.position <= self.role.position:
            issues.append(
                f"{EMOJI_ERROR} **Bot's role is below your custom role in the hierarchy.**\n"
                f"Go to Server Settings → Roles and drag the bot's role above **{self.role.name}**."
            )

        if issues:
            embed = discord.Embed(
                title=f"{EMOJI_ERROR} **Can't set icon right now**",
                description="\n\n".join(issues) + f"\n\n*Run `!testrole` for a full diagnosis.*",
                color=discord.Color.red()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await send_then_delete(interaction, embed, delay=10)
            return

        embed = discord.Embed(title=f"{EMOJI_GEAR} **Choose Icon Source**", description="Select how you want to set the role icon.", color=discord.Color.blue())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Upload", value="Upload an image file from your device", inline=True)
        embed.add_field(name="URL", value="Paste a direct image URL", inline=True)
        embed.add_field(name="Emoji", value="Use a custom emoji ID", inline=True)
        view = IconSelectionView(self.role, self.role_id, self.user_id, self.original_message)
        await self.original_message.edit(embed=embed, view=view)

    async def role_style_color_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        is_owner = interaction.user.id == self.user_id
        is_admin = interaction.user.guild_permissions.administrator
        if not is_owner and not is_admin:
            embed = discord.Embed(
                description=f"{EMOJI_ERROR} **Only the role owner can change the role style.**",
                color=discord.Color.red()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await send_then_delete(interaction, embed)
            return
        if not await can_user_use_gradient(interaction.user, interaction.guild):
            embed = discord.Embed(
                description=(
                    f"{EMOJI_ERROR} **You don't have gradient permission.**\n"
                    f"Gradient access is granted by an admin or awarded to the top-boosted role owner."
                ),
                color=discord.Color.red()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await send_then_delete(interaction, embed)
            return
        embed = discord.Embed(
            title=f"{BTN_GRADIENT} **Enhance Color**",
            description="Choose a style for your role color:",
            color=self.role.color
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Gradient", value="Pick two custom colors for a gradient effect", inline=True)
        embed.add_field(name="Holographic", value="Apply a preset holographic color scheme", inline=True)
        view = RoleStyleColorView(self.role, self.role_id, self.guild, self.original_message, self.user_id)
        await self.original_message.edit(embed=embed, view=view)

    async def back_button(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await update_role_info_display(self.original_message, self.role, self.role_id, owner_id=self.user_id)


# ---------- Enhance Color Sub-View ----------
HOLOGRAPHIC_COLOR1 = 0x00c6ff   # cyan-blue
HOLOGRAPHIC_COLOR2 = 0xff87c2   # soft pink

class RoleStyleColorView(DisableOnTimeoutView):
    def __init__(self, role: discord.Role, role_id: int, guild: discord.Guild, original_message: discord.Message, user_id: int = 0):
        super().__init__(timeout=120)
        self.role = role
        self.role_id = role_id
        self.guild = guild
        self.original_message = original_message
        self.user_id = user_id

    @discord.ui.button(emoji=BTN_GRADIENT, label="Gradient", style=discord.ButtonStyle.success)
    async def gradient_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner = interaction.user.id == self.user_id
        is_admin = interaction.user.guild_permissions.administrator
        if not is_owner and not is_admin:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Only the role owner can do this.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        if not await can_user_use_gradient(interaction.user, interaction.guild):
            embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have gradient permission.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        modal = GradientModal(self.role, self.role_id, self.guild, self.original_message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Holographic", style=discord.ButtonStyle.primary)
    async def holographic_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner = interaction.user.id == self.user_id
        is_admin = interaction.user.guild_permissions.administrator
        if not is_owner and not is_admin:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Only the role owner can do this.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        if not await can_user_use_gradient(interaction.user, interaction.guild):
            embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have gradient permission.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        await interaction.response.defer()
        with get_db() as conn:
            conn.execute(
                "UPDATE custom_roles SET gradient_colors = ? WHERE role_id = ?",
                (f"{HOLOGRAPHIC_COLOR1},{HOLOGRAPHIC_COLOR2}", self.role_id)
            )
            conn.commit()
        color_note = ""
        try:
            await _apply_gradient_to_role(self.role, HOLOGRAPHIC_COLOR1, HOLOGRAPHIC_COLOR2)
        except Exception as ce:
            color_note = f"\n{EMOJI_WARNING} *Could not apply gradient to role — check bot permissions and role hierarchy: {ce}*"
        embed = discord.Embed(
            description=(
                f"{EMOJI_SUCCESS} **Holographic gradient applied!**\n"
                f"Color 1: `{int_to_hex(HOLOGRAPHIC_COLOR1)}` · Color 2: `{int_to_hex(HOLOGRAPHIC_COLOR2)}`{color_note}"
            ),
            color=discord.Color(HOLOGRAPHIC_COLOR1)
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.followup.send(embed=embed)
        await update_role_info_display(self.original_message, self.role, self.role_id)

    @discord.ui.button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        gradient_allowed = await can_user_use_gradient(interaction.user, interaction.guild)
        embed = discord.Embed(
            title=f"{EMOJI_HAMMER} **Role Editing**",
            description="Choose what you'd like to change.",
            color=self.role.color
        )
        view = RoleEditView(self.role, self.role_id, self.user_id, self.guild, self.original_message, gradient_allowed=gradient_allowed)
        await self.original_message.edit(embed=embed, view=view)

# ---------- Member List Views ----------
class MemberDetailView(DisableOnTimeoutView):
    def __init__(self, role: discord.Role, role_id: int, target_user: discord.User, original_message: discord.Message, original_view, owner_id: int = 0):
        super().__init__(timeout=120)
        self.role = role
        self.role_id = role_id
        self.target_user = target_user
        self.original_message = original_message
        self.original_view = original_view
        self.owner_id = owner_id

    async def update_display(self, interaction: discord.Interaction):
        with get_db() as conn:
            cur = conn.execute("SELECT granted_at FROM role_memberships WHERE role_id = ? AND user_id = ?", (self.role_id, self.target_user.id))
            row = cur.fetchone()
            granted_at = row[0] if row else None
        boost_count = await get_user_votes_for_role(self.target_user.id, self.role_id, interaction.guild.id)
        embed = discord.Embed(title=f"📋 **Member Details**", color=self.role.color)
        embed.set_author(name=interaction.user.display_name, icon_url=self.target_user.avatar.url if self.target_user.avatar else None)
        embed.set_thumbnail(url=self.target_user.avatar.url if self.target_user.avatar else None)
        embed.add_field(name=f"{EMOJI_USER} User", value=self.target_user.mention, inline=False)
        embed.add_field(name=f"{EMOJI_BOOSTED_COUNT} Boosted Count", value=str(boost_count), inline=False)
        embed.add_field(name=f"{EMOJI_CALENDAR} Date Added", value=f"<t:{int(granted_at.timestamp())}:R>" if granted_at else "Unknown", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji=EMOJI_DELETE)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner = interaction.user.id == self.owner_id
        is_admin = interaction.user.guild_permissions.administrator
        if not is_owner and not is_admin:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Only the role owner can remove members.**", color=discord.Color.red())
            await send_then_delete(interaction, embed)
            return
        member = interaction.guild.get_member(self.target_user.id)
        if member and self.role in member.roles:
            await member.remove_roles(self.role)
        with get_db() as conn:
            conn.execute("DELETE FROM role_memberships WHERE role_id = ? AND user_id = ?", (self.role_id, self.target_user.id))
            conn.commit()
        success_embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Removed {self.target_user.mention} from the role.**", color=discord.Color.green())
        success_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.response.send_message(embed=success_embed, ephemeral=True)
        await self.original_view.show_members(interaction, direct_edit=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.original_view.show_members(interaction, direct_edit=False)

class RoleMembersView(DisableOnTimeoutView):
    def __init__(self, role: discord.Role, role_id: int, original_message: discord.Message, original_role_info_view):
        super().__init__(timeout=120)
        self.role = role
        self.role_id = role_id
        self.original_message = original_message
        self.original_role_info_view = original_role_info_view

    async def show_members(self, interaction: discord.Interaction = None, direct_edit: bool = False):
        members_data = await get_role_members(self.role_id)
        if not members_data:
            embed = discord.Embed(description=f"{EMOJI_WARNING} **No members have this role.**", color=discord.Color.orange())
            embed.set_author(name=self.role.name, icon_url=self.role.guild.icon.url if self.role.guild.icon else None)
            if interaction:
                if direct_edit:
                    await self.original_message.edit(embed=embed, view=self)
                else:
                    await interaction.response.edit_message(embed=embed, view=self)
            else:
                await self.original_message.edit(embed=embed, view=self)
            return

        options = []
        for user_id, granted_at in members_data:
            member = self.original_message.guild.get_member(user_id)
            if member:
                label = member.display_name[:100]
                options.append(discord.SelectOption(label=label, value=str(user_id)))
        if not options:
            embed = discord.Embed(description=f"{EMOJI_WARNING} **No valid members found (users may have left).**", color=discord.Color.orange())
            embed.set_author(name=self.role.name, icon_url=self.role.guild.icon.url if self.role.guild.icon else None)
            if interaction:
                if direct_edit:
                    await self.original_message.edit(embed=embed, view=self)
                else:
                    await interaction.response.edit_message(embed=embed, view=self)
            else:
                await self.original_message.edit(embed=embed, view=self)
            return

        select = discord.ui.Select(placeholder="Select a member...", options=options[:25], min_values=1, max_values=1)
        async def select_callback(select_interaction: discord.Interaction):
            user_id = int(select.values[0])
            user = select_interaction.guild.get_member(user_id)
            if not user:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **User not found.**", color=discord.Color.red())
                await select_interaction.response.send_message(embed=embed, ephemeral=True)
                return
            owner_id = getattr(self.original_role_info_view, "user_id", 0)
            detail_view = MemberDetailView(self.role, self.role_id, user, self.original_message, self, owner_id=owner_id)
            await detail_view.update_display(select_interaction)
        select.callback = select_callback

        self.clear_items()
        self.add_item(select)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
        back.callback = self.back_callback
        self.add_item(back)

        member_lines = []
        for uid, g_at in members_data[:10]:
            m = self.original_message.guild.get_member(uid)
            if m:
                with get_db() as _c:
                    _r = _c.execute("SELECT COUNT(*) FROM vote_log WHERE user_id=? AND role_id=?", (uid, self.role_id)).fetchone()
                    boost_count = _r[0] if _r else 0
                member_lines.append(f"• {m.mention} {EMOJI_BOOSTED} **{boost_count}**")
        member_desc = "\n".join(member_lines) if member_lines else "No members found."
        embed = discord.Embed(title=f"{EMOJI_MEMBERS} **Members of {self.role.name}**", description=member_desc, color=self.role.color)
        embed.set_author(name=self.role.name, icon_url=self.role.guild.icon.url if self.role.guild.icon else None)
        if interaction:
            if direct_edit:
                await self.original_message.edit(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            await self.original_message.edit(embed=embed, view=self)

    async def back_callback(self, interaction: discord.Interaction):
        await self.original_role_info_view.return_to_role_info(interaction)

class RoleInfoView(DisableOnTimeoutView):
    def __init__(self, role: discord.Role, role_id: int, user_id: int, guild: discord.Guild, original_message: discord.Message):
        super().__init__(timeout=120)
        self.role = role
        self.role_id = role_id
        self.user_id = user_id
        self.guild = guild
        self.original_message = original_message

    async def return_to_role_info(self, interaction: discord.Interaction):
        await update_role_info_display(self.original_message, self.role, self.role_id, owner_id=self.user_id)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji=BTN_PENCIL, label="Edit", style=discord.ButtonStyle.primary, row=0)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        gradient_allowed = await can_user_use_gradient(interaction.user, interaction.guild)
        embed = discord.Embed(title=f"{EMOJI_HAMMER} **Role Editing**", description="Choose what you'd like to change.\n\nBe careful not to break any server rules.", color=self.role.color)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Name", value="Change the role name", inline=True)
        embed.add_field(name="Color", value="Change the role color (hex code)", inline=True)
        embed.add_field(name="Icon", value="Set a custom icon (upload, URL, or emoji)", inline=True)
        style_note = "Set gradient or holographic colors" if gradient_allowed else "🔒 Win weekly boost ranking or get permission"
        embed.add_field(name="Enhance Color", value=style_note, inline=True)
        view = RoleEditView(self.role, self.role_id, self.user_id, self.guild, self.original_message, gradient_allowed=gradient_allowed)
        await self.original_message.edit(embed=embed, view=view)

    @discord.ui.button(emoji=EMOJI_STAR, label="Display", style=discord.ButtonStyle.success, row=0)
    async def highlight_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_highlight_menu(interaction, self.role, self.role_id, self.original_message, self)

    @discord.ui.button(emoji=EMOJI_MEMBERS, label="Members", style=discord.ButtonStyle.success, row=0)
    async def members_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RoleMembersView(self.role, self.role_id, self.original_message, self)
        await view.show_members(interaction)

    @discord.ui.button(emoji=BTN_BACK, label="Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.role = interaction.guild.get_role(self.role_id) or self.role
        await update_role_info_display(self.original_message, self.role, self.role_id, owner_id=self.user_id)

class HighlightSelect(discord.ui.Select):
    def __init__(self, user_roles: list, guild_id: int, user_id: int, original_message: discord.Message, parent_view):
        self.guild_id = guild_id
        self.user_id = user_id
        self.original_message = original_message
        self.parent_view = parent_view
        options = []
        for role in user_roles[:25]:
            options.append(discord.SelectOption(label=role.name[:100], value=str(role.id)))
        options.append(discord.SelectOption(label="Remove Display", value="none", emoji=EMOJI_DELETE, description="Remove displayed role"))
        super().__init__(placeholder="Select a role to display at the top...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild
        bot_member = guild.me
        if self.values[0] == "none":
            await set_highlighted_role(member, None)
            embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Display role removed.**", color=discord.Color.green())
            embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
            await send_then_delete(interaction, embed)
            await update_display_menu(self.original_message, guild, member.id, self.parent_view)
        else:
            role_id = int(self.values[0])
            role = guild.get_role(role_id)
            if role not in member.roles:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have that role.**", color=discord.Color.red())
                embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
                await send_then_delete(interaction, embed)
                return
            elif role.position >= bot_member.top_role.position:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **I cannot manage that role** because it's above my highest role.\n\nMove my role ({bot_member.top_role.mention}) above {role.mention}.", color=discord.Color.red())
                embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
                await send_then_delete(interaction, embed)
                return
            else:
                success = await set_highlighted_role(member, role_id)
                if success:
                    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{role.name} is now your display role!** It will appear at the top of your profile.", color=role.color)
                    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
                    await send_then_delete(interaction, embed)
                    await update_display_menu(self.original_message, guild, member.id, self.parent_view)
                else:
                    embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed to reorder roles.** Make sure my role is above {role.mention}.", color=discord.Color.red())
                    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
                    await send_then_delete(interaction, embed)

class HighlightView(DisableOnTimeoutView):
    def __init__(self, user_roles: list, guild_id: int, user_id: int, original_message: discord.Message, role_info_view: RoleInfoView):
        super().__init__(timeout=60)
        self.role_info_view = role_info_view
        self.add_item(HighlightSelect(user_roles, guild_id, user_id, original_message, self))
        if role_info_view:
            back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
            back.callback = self.back_callback
            self.add_item(back)

    async def back_callback(self, interaction: discord.Interaction):
        await self.role_info_view.return_to_role_info(interaction)

async def update_display_menu(message: discord.Message, guild: discord.Guild, user_id: int, parent_view: HighlightView = None):
    member = guild.get_member(user_id)
    if not member:
        return
    user_roles = [r for r in member.roles if r.name != "@everyone"]
    bot_member = guild.me
    manageable_roles = [r for r in user_roles if r.position < bot_member.top_role.position]
    embed = discord.Embed(title=f"{EMOJI_STAR} **Role Placement**", description="Select a role to appear at the **top** of your profile.\n\nThis role will be displayed above all your other roles.", color=discord.Color.blue())
    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
    current = await get_highlighted_role(user_id, guild.id)
    if current:
        current_role = guild.get_role(current)
        if current_role:
            embed.add_field(name="**Currently Displayed**", value=f"{EMOJI_STAR} {current_role.mention}", inline=False)
    embed.set_footer(text=f"Roles above {bot_member.top_role.mention} cannot be managed")
    role_info_view = parent_view.role_info_view if parent_view else None
    view = HighlightView(manageable_roles, guild.id, user_id, message, role_info_view)
    await message.edit(embed=embed, view=view)

async def show_highlight_menu(interaction: discord.Interaction, role: discord.Role, role_id: int, original_message: discord.Message, role_info_view: RoleInfoView):
    await interaction.response.defer()
    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    user_roles = [r for r in member.roles if r.name != "@everyone"]
    manageable_roles = [r for r in user_roles if r.position < bot_member.top_role.position]
    if not manageable_roles:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have any roles I can manage.**\n\nMake sure my role ({bot_member.top_role.mention}) is above the roles you want to display.", color=discord.Color.red())
        embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
        await send_then_delete(interaction, embed)
        return
    embed = discord.Embed(title=f"{EMOJI_STAR} **Role Placement**", description="Select a role to appear at the **top** of your profile.\n\nThis role will be displayed above all your other roles.", color=discord.Color.blue())
    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
    current = await get_highlighted_role(interaction.user.id, interaction.guild.id)
    if current:
        current_role = guild.get_role(current)
        if current_role:
            embed.add_field(name="**Currently Displayed**", value=f"{EMOJI_STAR} {current_role.mention}", inline=False)
    embed.set_footer(text=f"Roles above {bot_member.top_role.mention} cannot be managed")
    view = HighlightView(manageable_roles, guild.id, member.id, original_message, role_info_view)
    await original_message.edit(embed=embed, view=view)

async def update_role_info_display(message: discord.Message, role: discord.Role, role_id: int, owner_id: int = None):
    with get_db() as conn:
        cur = conn.execute("SELECT name, icon_url FROM custom_roles WHERE role_id = ?", (role_id,))
        row = cur.fetchone()
        if not row:
            return
        name, icon_url = row

    if owner_id is None:
        with get_db() as conn:
            cur = conn.execute("SELECT owner_id FROM custom_roles WHERE role_id = ?", (role_id,))
            row2 = cur.fetchone()
            if row2:
                owner_id = row2[0]
    if owner_id:
        user = message.guild.get_member(owner_id) or await message.guild.fetch_member(owner_id)
        avatar_url = user.avatar.url if user and user.avatar else None
    else:
        avatar_url = None

    owner_name = "Unknown"
    if owner_id:
        _owner = message.guild.get_member(owner_id)
        if _owner:
            owner_name = _owner.display_name
    embed = discord.Embed(title="Role Information", color=role.color)
    embed.set_author(name=owner_name, icon_url=avatar_url)
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    embed.add_field(name=f"{EMOJI_MEMO} Name", value=f"`{name}`", inline=False)
    embed.add_field(name=f"{EMOJI_COLOR} Color", value=f"`{int_to_hex(role.color.value)}`", inline=False)

    view = RoleInfoView(role, role_id, owner_id or message.author.id, message.guild, message)
    await message.edit(embed=embed, view=view)

# ---------- Boost Confirmation View (single embed) ----------
class BoostConfirmView(DisableOnTimeoutView):
    def __init__(self, user: discord.Member, role: discord.Role, votes: int, daily_rem: int, extra_rem: int, original_interaction: discord.Interaction):
        super().__init__(timeout=30)
        self.user = user
        self.role = role
        self.votes = votes
        self.daily_rem = daily_rem
        self.extra_rem = extra_rem
        self.original_interaction = original_interaction

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        success, daily_used, extra_used = await use_vote(self.user, interaction.guild.id, self.votes)
        if not success:
            embed = discord.Embed(description=f"{EMOJI_ERROR} Failed to use boosts.", color=discord.Color.red())
            await interaction.response.edit_message(embed=embed, view=None)
            return
        await add_vote_to_role(self.role.id, interaction.guild.id, self.user.id, self.votes)
        cur = conn2 = None
        with get_db() as conn2:
            cur = conn2.execute("SELECT owner_id FROM custom_roles WHERE role_id = ?", (self.role.id,))
            owner_row = cur.fetchone()
        if owner_row:
            await create_boost_notification(owner_row[0], interaction.guild.id, self.role.id, self.user.id, self.votes)
        embed = discord.Embed(description=f"{EMOJI_BOOSTED} You boosted {self.role.mention} using {extra_used} extra boost(s)!", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(description=f"{EMOJI_WARNING} Boost cancelled.", color=discord.Color.orange())
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

class UnboostConfirmView(DisableOnTimeoutView):
    def __init__(self, user: discord.Member, role: discord.Role, owner: discord.Member, votes: int, daily_rem: int, extra_rem: int, ctx):
        super().__init__(timeout=30)
        self.user = user
        self.role = role
        self.owner = owner
        self.votes = votes
        self.daily_rem = daily_rem
        self.extra_rem = extra_rem
        self.ctx = ctx

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJI_ERROR} **Not your action.**", color=discord.Color.red()),
                ephemeral=True
            )
            return
        role_total_before = await get_total_votes_on_role(self.role.id, interaction.guild.id)
        votes_to_remove = min(self.votes, role_total_before)
        success, daily_used, extra_used = await use_vote(self.user, interaction.guild.id, votes_to_remove)
        if not success:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed to spend boosts.**", color=discord.Color.red())
            await interaction.response.edit_message(embed=embed, view=None)
            return
        removed = await remove_any_votes_from_role(self.role.id, interaction.guild.id, votes_to_remove)
        new_role_total = role_total_before - removed
        new_daily = self.daily_rem - daily_used
        new_extra = self.extra_rem - extra_used
        embed = discord.Embed(
            description=(
                f"{EMOJI_DELETE} **Removed {removed} boost(s) from {self.role.mention} (owned by {self.owner.mention}) using extra boosts.**\n"
                f"Role total boosts: **{new_role_total}**\n"
                f"Your remaining — daily: **{new_daily}**, extra: **{new_extra}**"
            ),
            color=discord.Color.orange()
        )
        embed.set_author(name=self.user.display_name, icon_url=self.user.avatar.url if self.user.avatar else None)
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJI_ERROR} **Not your action.**", color=discord.Color.red()),
                ephemeral=True
            )
            return
        embed = discord.Embed(description=f"{EMOJI_WARNING} **Unboost cancelled.**", color=discord.Color.orange())
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


# ---------- Overview Multi‑Page View ----------
class OverviewView(DisableOnTimeoutView):
    def __init__(self, guild: discord.Guild, user: discord.User, page: int = 0, mode: str = "rankings"):
        super().__init__(timeout=120)
        self.guild = guild
        self.user = user
        self.page = page
        self.mode = mode
        self.items_per_page = 10
        self.embed = None
        self.total_pages = 1
        self._skip_trend = False

    async def initialize(self):
        await self.update_embed()

    def _get_author_name(self):
        if self.mode == "rankings":
            return "Role Overview | Weekly Rankings"
        else:
            return f"Role Overview ({self.page + 1}/{self.total_pages})"

    async def update_embed(self):
        if self.mode == "rankings":
            await self._update_rankings()
        elif self.mode == "creators":
            await self._update_creators()
        elif self.mode == "most_users":
            await self._update_most_users()

        self.clear_items()

        # ── Boost select (rankings only) ───────────────────────────────────
        if self.mode == "rankings":
            member = self.guild.get_member(self.user.id) or self.user
            daily_rem = await get_daily_votes_remaining(self.user.id, self.guild.id)
            if daily_rem == -1:
                total_daily = await get_user_total_votes(member, self.guild.id)
                await reset_daily_votes(self.user.id, self.guild.id, total_daily)
                daily_rem = total_daily
            extra_rem = await get_user_extra_votes(self.user.id, self.guild.id)
            total_rem = daily_rem + extra_rem

            if total_rem > 0:
                roles = await get_all_custom_roles(self.guild.id)
                weekly = await get_weekly_votes(self.guild.id)
                options = []
                for role_id, name, owner_id, icon_url in roles:
                    role = self.guild.get_role(role_id)
                    if role:
                        boost_count = weekly.get(role_id, 0)
                        options.append(discord.SelectOption(
                            label=role.name[:100],
                            value=str(role_id),
                            description=f"{boost_count} boosts"
                        ))
                options.sort(key=lambda opt: int(weekly.get(int(opt.value), 0)), reverse=True)
                if options:
                    boost_select = discord.ui.Select(
                        placeholder="Select A Role To Boost",
                        options=options[:25],
                        min_values=1, max_values=1,
                        row=0
                    )
                    async def boost_callback(interaction: discord.Interaction):
                        role_id = int(boost_select.values[0])
                        role = self.guild.get_role(role_id)
                        if not role:
                            embed = discord.Embed(description=f"{EMOJI_ERROR} Role not found.", color=discord.Color.red())
                            await interaction.response.send_message(embed=embed, ephemeral=True)
                            return
                        _member = self.guild.get_member(self.user.id) or self.user
                        daily_rem2 = await get_daily_votes_remaining(self.user.id, self.guild.id)
                        if daily_rem2 == -1:
                            total_daily2 = await get_user_total_votes(_member, self.guild.id)
                            await reset_daily_votes(self.user.id, self.guild.id, total_daily2)
                            daily_rem2 = total_daily2
                        extra_rem2 = await get_user_extra_votes(self.user.id, self.guild.id)
                        if daily_rem2 >= 1:
                            success, _, _ = await use_vote(_member, self.guild.id, 1)
                            if not success:
                                embed = discord.Embed(description=f"{EMOJI_ERROR} Failed to use boost.", color=discord.Color.red())
                                await interaction.response.send_message(embed=embed, ephemeral=True)
                                return
                            await add_vote_to_role(role_id, self.guild.id, self.user.id, 1)
                            with get_db() as _conn:
                                _cur = _conn.execute("SELECT owner_id FROM custom_roles WHERE role_id = ?", (role_id,))
                                _owner_row = _cur.fetchone()
                            if _owner_row:
                                await create_boost_notification(_owner_row[0], self.guild.id, role_id, self.user.id, 1)
                            self._skip_trend = True
                            await self.update_embed()
                            self._skip_trend = False
                            await interaction.response.edit_message(embed=self.embed, view=self)
                        elif extra_rem2 >= 1:
                            view = BoostConfirmView(_member, role, 1, daily_rem2, extra_rem2, interaction)
                            embed = discord.Embed(
                                description=f"{EMOJI_WARNING} **Your daily boosts are over.**\nYou have **{extra_rem2}** extra boost(s) left.\nUse **1 extra boost** to boost {role.mention}?",
                                color=discord.Color.orange()
                            )
                            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                        else:
                            embed = discord.Embed(description=f"{EMOJI_ERROR} You have no boosts left!", color=discord.Color.red())
                            await interaction.response.send_message(embed=embed, ephemeral=True)
                    boost_select.callback = boost_callback
                    self.add_item(boost_select)
            else:
                disabled_select = discord.ui.Select(
                    placeholder="Select A Role To Boost",
                    options=[discord.SelectOption(label="No boosts left", value="0")],
                    disabled=True,
                    row=0
                )
                self.add_item(disabled_select)

        # ── Mode selector ──────────────────────────────────────────────────
        mode_select = discord.ui.Select(
            placeholder="Select view...",
            options=[
                discord.SelectOption(label="Weekly Rankings", value="rankings", emoji=EMOJI_STAR, default=self.mode == "rankings"),
                discord.SelectOption(label="Role Creators", value="creators", emoji=EMOJI_USER, default=self.mode == "creators"),
                discord.SelectOption(label="Most Users", value="most_users", emoji=EMOJI_MOST_USERS, default=self.mode == "most_users"),
            ],
            row=1
        )
        async def select_callback(interaction: discord.Interaction):
            self.mode = mode_select.values[0]
            self.page = 0
            await self.update_embed()
            await interaction.response.edit_message(embed=self.embed, view=self)
        mode_select.callback = select_callback
        self.add_item(mode_select)

        # ── Navigation: ◄ Previous | page/total (label) | Next ► ─────────
        prev_btn = discord.ui.Button(
            emoji=BTN_PREV, label="Previous",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page == 0),
            row=2
        )
        page_btn = discord.ui.Button(
            label=f"{self.page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=2
        )
        next_btn = discord.ui.Button(
            emoji=BTN_NEXT, label="Next",
            style=discord.ButtonStyle.success,
            disabled=(self.page >= self.total_pages - 1),
            row=2
        )
        prev_btn.callback = self._prev_callback
        next_btn.callback = self._next_callback
        self.add_item(prev_btn)
        self.add_item(page_btn)
        self.add_item(next_btn)

        # ── Load Users button ──────────────────────────────────────────────
        load_btn = discord.ui.Button(
            emoji=EMOJI_USER, label="Load Users",
            style=discord.ButtonStyle.primary,
            row=3
        )
        async def load_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                await self.guild.chunk()
            except Exception:
                pass
            await self.update_embed()
            await interaction.edit_original_response(embed=self.embed, view=self)
        load_btn.callback = load_callback
        self.add_item(load_btn)

    async def _prev_callback(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            await self.update_embed()
            await interaction.response.edit_message(embed=self.embed, view=self)

    async def _next_callback(self, interaction: discord.Interaction):
        if self.page < self.total_pages - 1:
            self.page += 1
            await self.update_embed()
            await interaction.response.edit_message(embed=self.embed, view=self)

    async def _update_rankings(self):
        roles = await get_all_custom_roles(self.guild.id)
        weekly = await get_weekly_votes(self.guild.id)
        last_week = await get_last_week_votes(self.guild.id)
        role_data = []
        for role_id, name, owner_id, icon_url in roles:
            w = weekly.get(role_id, 0)
            lw = last_week.get(role_id, 0)
            role_data.append((role_id, w, lw, name, owner_id, icon_url))
        role_data.sort(key=lambda x: x[1], reverse=True)
        self.total_pages = (len(role_data) + self.items_per_page - 1) // self.items_per_page
        start = self.page * self.items_per_page
        end = min(start + self.items_per_page, len(role_data))
        page_data = role_data[start:end]

        member = self.guild.get_member(self.user.id) or self.user
        daily_rem = await get_daily_votes_remaining(self.user.id, self.guild.id)
        if daily_rem == -1:
            total_daily = await get_user_total_votes(member, self.guild.id)
            await reset_daily_votes(self.user.id, self.guild.id, total_daily)
            daily_rem = total_daily
        else:
            total_daily = await get_user_total_votes(member, self.guild.id)
        extra_rem = await get_user_extra_votes(self.user.id, self.guild.id)

        with get_db() as conn:
            cur = conn.execute("SELECT last_reset FROM user_votes WHERE user_id = ? AND guild_id = ?",
                               (self.user.id, self.guild.id))
            row = cur.fetchone()
        if row and row[0]:
            last_reset = row[0]
            if last_reset.tzinfo is None:
                last_reset = last_reset.replace(tzinfo=timezone.utc)
            next_reset = last_reset + timedelta(hours=12)
            reset_timestamp = int(next_reset.timestamp())
            reset_text = f"<t:{reset_timestamp}:R>"
        else:
            reset_text = "now"

        now = datetime.now(timezone.utc)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_yesterday = start_of_today - timedelta(days=1)
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

        # Build today's and yesterday's boost counts per role
        with get_db() as conn:
            today_rows = conn.execute(
                "SELECT role_id, COUNT(*) FROM vote_log WHERE guild_id=? AND voted_at >= ? GROUP BY role_id",
                (self.guild.id, start_of_today)
            ).fetchall()
            yesterday_rows = conn.execute(
                "SELECT role_id, COUNT(*) FROM vote_log WHERE guild_id=? AND voted_at >= ? AND voted_at < ? GROUP BY role_id",
                (self.guild.id, start_of_yesterday, start_of_today)
            ).fetchall()
            cur = conn.execute("""
                SELECT role_id FROM vote_log
                WHERE user_id = ? AND guild_id = ? AND voted_at >= ?
                ORDER BY voted_at DESC LIMIT 1
            """, (self.user.id, self.guild.id, start_of_week))
            boosted_row = cur.fetchone()
        today_counts = {rid: cnt for rid, cnt in today_rows}
        yesterday_counts = {rid: cnt for rid, cnt in yesterday_rows}
        boosted_role = self.guild.get_role(boosted_row[0]) if boosted_row else None
        boosted_text = boosted_role.mention if boosted_role else "None yet"

        guild_icon = self.guild.icon.url if self.guild.icon else None
        lines = [f"{EMOJI_ROLE_RANKS} **Vote once per day** to {EMOJI_STAR} boost your favorite role\n"]
        for idx, (role_id, w, lw, name, owner_id, icon_url) in enumerate(page_data, start=start + 1):
            role = self.guild.get_role(role_id)
            if not role:
                continue
            t = today_counts.get(role_id, 0)
            y = yesterday_counts.get(role_id, 0)
            # Up: today received MORE votes than yesterday (gaining momentum)
            # Down: today received FEWER votes than yesterday (losing momentum)
            # Flat/no trend: same count or no votes either day
            if self._skip_trend:
                trend = ""
            elif t > y:
                trend = f"{EMOJI_TRENDING_UP} **+{t - y}**"
            elif y > 0 and t < y:
                trend = f"{EMOJI_TRENDING_DOWN} **-{y - t}**"
            else:
                trend = ""
            line = f"**#{idx}** {role.mention} - **{w} boosts**"
            if trend:
                line += f" {trend}"
            lines.append(line)

        now = datetime.now(timezone.utc)
        next_monday = (now + timedelta(days=7 - now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        lines += [
            "",
            f"{EMOJI_DAILY} **Daily Boosts:** {daily_rem}/{total_daily} – resets {reset_text}",
        ]
        if extra_rem > 0:
            lines.append(f"{EMOJI_EXTRA_BOOST} **Extra Boosts:** {extra_rem} available")
        else:
            lines.append(f"{EMOJI_EXTRA_BOOST} **Extra Boosts:** None")
        lines += [
            f"{EMOJI_BOOSTED} **You have boosted:** {boosted_text}",
            "",
            f"{EMOJI_BOOSTED_COUNT} The top role each week can choose a custom gradient color",
            f"{EMOJI_CALENDAR} Next reshuffle <t:{int(next_monday.timestamp())}:R>",
            "",
            f"{EMOJI_INFO} Roles reorder weekly based on these rankings",
        ]

        embed = discord.Embed(description="\n".join(lines), color=discord.Color.gold())
        embed.set_author(name=self._get_author_name(), icon_url=guild_icon)
        self.embed = embed

    async def _update_creators(self):
        roles = await get_all_custom_roles(self.guild.id)
        role_data = sorted(roles, key=lambda x: x[1])
        self.total_pages = max(1, (len(role_data) + self.items_per_page - 1) // self.items_per_page)
        start = self.page * self.items_per_page
        end = min(start + self.items_per_page, len(role_data))
        page_data = role_data[start:end]

        guild_icon = self.guild.icon.url if self.guild.icon else None
        lines = [f"{EMOJI_USER} View a list of roles and their creators\n", f"{EMOJI_STACK} __Roles__"]
        for idx, (role_id, name, owner_id, icon_url) in enumerate(page_data, start=start + 1):
            role = self.guild.get_role(role_id)
            owner = self.guild.get_member(owner_id)
            role_display = role.mention if role else name
            owner_mention = owner.mention if owner else f"<@{owner_id}>"
            lines.append(f"{idx}. {role_display} - {owner_mention}")

        embed = discord.Embed(description="\n".join(lines), color=discord.Color.blue())
        embed.set_author(name=self._get_author_name(), icon_url=guild_icon)
        self.embed = embed

    async def _update_most_users(self):
        roles = await get_all_custom_roles(self.guild.id)
        role_counts = []
        for role_id, name, owner_id, icon_url in roles:
            count = await get_role_member_count(role_id, self.guild.id)
            role_counts.append((role_id, count, name, owner_id, icon_url))
        role_counts.sort(key=lambda x: x[1], reverse=True)
        self.total_pages = max(1, (len(role_counts) + self.items_per_page - 1) // self.items_per_page)
        start = self.page * self.items_per_page
        end = min(start + self.items_per_page, len(role_counts))
        page_data = role_counts[start:end]

        guild_icon = self.guild.icon.url if self.guild.icon else None
        lines = [f"{EMOJI_MOST_USERS} View roles sorted by user count (highest first)\n", f"{EMOJI_STACK} __Roles__"]
        for idx, (role_id, count, name, owner_id, icon_url) in enumerate(page_data, start=start + 1):
            role = self.guild.get_role(role_id)
            role_display = role.mention if role else name
            lines.append(f"{idx}. {role_display} - {EMOJI_MEMBERS} **{count} Users**")

        embed = discord.Embed(description="\n".join(lines), color=discord.Color.blue())
        embed.set_author(name=self._get_author_name(), icon_url=guild_icon)
        self.embed = embed

# ---------- Gradient Permission Admin View (fixed) ----------
class GradientPermissionView(DisableOnTimeoutView):
    def __init__(self, guild: discord.Guild, original_interaction: discord.Interaction):
        super().__init__(timeout=120)
        self.guild = guild
        self.original_interaction = original_interaction
        self.message = None

    async def get_role_owners(self):
        roles = await get_all_custom_roles(self.guild.id)
        owners = {}
        for role_id, name, owner_id, icon_url in roles:
            if owner_id not in owners:
                owner = self.guild.get_member(owner_id)
                if owner:
                    owners[owner_id] = owner.display_name
                else:
                    owners[owner_id] = f"Unknown User ({owner_id})"
        return owners

    async def refresh(self, interaction: discord.Interaction):
        owners = await self.get_role_owners()
        if not owners:
            embed = discord.Embed(description=f"{EMOJI_WARNING} No custom role owners found.", color=discord.Color.orange())
            embed.set_author(name="Gradient Access", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await interaction.edit_original_response(embed=embed, view=None)
            return

        options = []
        for user_id, name in owners.items():
            has_perm = await has_gradient_permission(user_id, self.guild.id)
            desc = f"Permission: {'✅ Granted' if has_perm else '❌ Not granted'}"
            options.append(discord.SelectOption(label=name, value=str(user_id), description=desc))
        
        select = discord.ui.Select(placeholder="Select a user to toggle gradient permission", options=options[:25], min_values=1, max_values=1)
        
        async def select_callback(select_interaction: discord.Interaction):
            user_id = int(select.values[0])
            user = self.guild.get_member(user_id)
            if not user:
                embed = discord.Embed(description=f"{EMOJI_ERROR} User not found.", color=discord.Color.red())
                await select_interaction.response.send_message(embed=embed, ephemeral=True)
                return
            has = await has_gradient_permission(user_id, self.guild.id)
            if has:
                await revoke_gradient_permission(user_id, self.guild.id)
                result_embed = discord.Embed(description=f"{EMOJI_SUCCESS} Removed gradient permission from {user.mention}.", color=discord.Color.green())
            else:
                await grant_gradient_permission(user_id, self.guild.id)
                result_embed = discord.Embed(description=f"{EMOJI_SUCCESS} Granted gradient permission to {user.mention}.\n*User must reopen their role info to see the gradient button.*", color=discord.Color.green())
            
            await select_interaction.response.send_message(embed=result_embed, ephemeral=True)
            await self.refresh(interaction)
        
        select.callback = select_callback
        self.clear_items()
        self.add_item(select)
        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
        back_btn.callback = self.back_callback
        self.add_item(back_btn)
        
        embed = discord.Embed(title=f"{BTN_GRADIENT} **Enhance Color Access**", description="Select a custom role owner to grant or revoke Enhance Color permission.\n\n*You can grant access regardless of server boost level — it will activate once the server reaches Boost Level 3.*", color=discord.Color.blue())
        embed.set_author(name="Enhance Color Access", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        
        if self.message is None:
            await interaction.response.edit_message(embed=embed, view=self)
            self.message = await interaction.original_response()
        else:
            await interaction.edit_original_response(embed=embed, view=self)

    async def back_callback(self, interaction: discord.Interaction):
        await _show_setup_embed(interaction, edit=True)

# ---------- Setup Embed Helper ----------
async def _show_setup_embed(interaction: discord.Interaction, edit: bool = False):
    """Build and show the main setup embed. edit=True uses edit_message, False sends new."""
    guild = interaction.guild
    user = interaction.user
    with get_db() as conn:
        cur = conn.execute(
            "SELECT prefix, role_add_whitelist, role_remove_whitelist, trigger_role_id FROM guild_config WHERE guild_id = ?",
            (guild.id,)
        )
        row = cur.fetchone()
        if not row:
            conn.execute(
                "INSERT INTO guild_config (guild_id, prefix, role_add_whitelist, role_remove_whitelist, trigger_role_id) VALUES (?, ?, ?, ?, ?)",
                (guild.id, "!", "", "", None)
            )
            conn.commit()
            prefix, add_whitelist, remove_whitelist, trigger_role_id = "!", "", "", None
        else:
            prefix, add_whitelist, remove_whitelist, trigger_role_id = row

    trigger_role_mention = "None"
    if trigger_role_id:
        tr = guild.get_role(trigger_role_id)
        if tr:
            trigger_role_mention = tr.mention

    def resolve_mentions(ids_str: str) -> str:
        if not ids_str:
            return "None (only admins)"
        ids = [x.strip() for x in ids_str.split(',') if x.strip().isdigit()]
        if not ids:
            return "None (only admins)"
        parts = []
        for id_str in ids:
            id_ = int(id_str)
            role = guild.get_role(id_)
            if role:
                parts.append(role.mention)
            else:
                member = guild.get_member(id_)
                parts.append(member.mention if member else f"`{id_str}`")
        return ', '.join(parts) if parts else "None (only admins)"

    embed = discord.Embed(title=f"{EMOJI_GEAR} **Bot Configuration**", color=discord.Color.blue())
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
    embed.add_field(name=f"{EMOJI_PIN} **Current Prefix**", value=f"`{prefix}`", inline=False)
    embed.add_field(name=f"{EMOJI_ADD} **Role Add Whitelist**", value=resolve_mentions(add_whitelist), inline=False)
    embed.add_field(name=f"{BTN_TRIGGER} **Trigger Role**", value=trigger_role_mention, inline=False)

    view = _make_setup_view(guild.id, prefix)
    if edit:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


def _make_setup_view(guild_id: int, prefix: str):
    class SetupView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self._guild_id = guild_id
            self._prefix = prefix

        @discord.ui.button(emoji=EMOJI_GEAR, label="Change Prefix", style=discord.ButtonStyle.primary)
        async def change_prefix(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            modal = discord.ui.Modal(title="Change Command Prefix")
            input_prefix = discord.ui.TextInput(label="New Prefix", placeholder="e.g., ! or ?", default=self._prefix)
            modal.add_item(input_prefix)
            async def on_submit(modal_interaction):
                new_prefix = input_prefix.value
                with get_db() as conn:
                    conn.execute("UPDATE guild_config SET prefix = ? WHERE guild_id = ?", (new_prefix, self._guild_id))
                    conn.commit()
                embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Prefix changed to `{new_prefix}`**", color=discord.Color.green())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
            modal.on_submit = on_submit
            await btn_interaction.response.send_modal(modal)

        @discord.ui.button(emoji=EMOJI_ADD, label="Whitelist Add", style=discord.ButtonStyle.secondary)
        async def whitelist_add(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            view = WhitelistSelectView(self._guild_id, "role_add")
            embed = discord.Embed(
                title=f"{EMOJI_ADD} **Whitelist — Role Add**",
                description="Select up to 10 users or roles to whitelist.\nThey can use role-add commands and all admin commands without being an administrator.",
                color=discord.Color.blue()
            )
            embed.set_author(name=btn_interaction.user.display_name, icon_url=btn_interaction.user.avatar.url if btn_interaction.user.avatar else None)
            await btn_interaction.response.edit_message(embed=embed, view=view)

        @discord.ui.button(emoji=BTN_TRIGGER, label="Set Trigger Role", style=discord.ButtonStyle.success)
        async def set_trigger_role(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            view = TriggerRoleSelectView(btn_interaction.guild.id, btn_interaction.guild)
            embed = discord.Embed(
                title=f"{BTN_TRIGGER} **Set Trigger Role**",
                description="Select a server role from the dropdown below.\nMembers who receive this role will automatically get a custom role created for them.\n\nClick **Clear Trigger Role** to remove it.",
                color=discord.Color.blue()
            )
            embed.set_author(name=btn_interaction.user.display_name, icon_url=btn_interaction.user.avatar.url if btn_interaction.user.avatar else None)
            await btn_interaction.response.edit_message(embed=embed, view=view)

        @discord.ui.button(emoji=BTN_GRADIENT, label="Enhance Color Access", style=discord.ButtonStyle.primary)
        async def gradient_access(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            view = GradientPermissionView(btn_interaction.guild, btn_interaction)
            await view.refresh(btn_interaction)

        @discord.ui.button(emoji=EMOJI_LVL_SETTINGS, label="Member's Level Up", style=discord.ButtonStyle.success)
        async def lvlup_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            ensure_lvl_config(btn_interaction.guild.id)
            view = LevelUpSetupView(btn_interaction.guild)
            embed = view.build_embed()
            await btn_interaction.response.edit_message(embed=embed, view=view)

        @discord.ui.button(emoji=EMOJI_DELETE, label="Clear Cache", style=discord.ButtonStyle.danger)
        async def clear_cache(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            embed = discord.Embed(
                title=f"{EMOJI_DELETE} **Clear Server Cache**",
                description=(
                    f"{EMOJI_WARNING} **This will permanently delete ALL bot data for this server:**\n\n"
                    f"- All custom roles and memberships\n"
                    f"- All votes, boosts, and extra boosts\n"
                    f"- All permissions and user settings\n"
                    f"- Server configuration (prefix, whitelist, trigger role)\n\n"
                    f"**This cannot be undone.** Are you sure?"
                ),
                color=discord.Color.red()
            )
            embed.set_author(name=btn_interaction.user.display_name, icon_url=btn_interaction.user.avatar.url if btn_interaction.user.avatar else None)
            view = ClearCacheConfirmView(btn_interaction.guild, btn_interaction.user)
            await btn_interaction.response.edit_message(embed=embed, view=view)

    return SetupView()


# ═══════════════════════════════════════════════════════════════════════════════
# Clear Cache Helper (fixed – deletes VC channels)
# ═══════════════════════════════════════════════════════════════════════════════

async def clear_server_data(guild_id: int, guild=None) -> dict:
    """Clear all bot data for a server. Returns a summary dict with counts."""
    summary = {
        "custom_roles_deleted": 0,
        "voice_channels_deleted": 0,
        "hub_channel_deleted": False,
        "errors": []
    }

    # First, collect all Discord channel IDs that need deleting
    vc_channel_ids = []
    hub_channel_id = None

    with get_db() as conn:
        cur = conn.execute("SELECT channel_id FROM vc_channels WHERE guild_id = ?", (guild_id,))
        vc_channel_ids = [row[0] for row in cur.fetchall()]
        cur = conn.execute("SELECT hub_channel_id FROM vc_hub WHERE guild_id = ?", (guild_id,))
        hub_row = cur.fetchone()
        if hub_row:
            hub_channel_id = hub_row[0]

    # Delete Discord channels (if guild object is provided)
    if guild:
        for cid in vc_channel_ids:
            ch = guild.get_channel(cid)
            if ch:
                try:
                    await ch.delete(reason="Server cache cleared by admin")
                    summary["voice_channels_deleted"] += 1
                except (discord.Forbidden, discord.HTTPException) as e:
                    summary["errors"].append(f"Could not delete VC {cid}: {e}")
                await asyncio.sleep(0.2)
            else:
                summary["voice_channels_deleted"] += 1
        if hub_channel_id:
            hub_ch = guild.get_channel(hub_channel_id)
            if hub_ch:
                try:
                    await hub_ch.delete(reason="Server cache cleared by admin")
                    summary["hub_channel_deleted"] = True
                except (discord.Forbidden, discord.HTTPException) as e:
                    summary["errors"].append(f"Could not delete hub channel: {e}")

    # Delete all database records
    with get_db() as conn:
        cur = conn.execute("SELECT role_id FROM custom_roles WHERE guild_id = ?", (guild_id,))
        role_ids = [row[0] for row in cur.fetchall()]
        summary["custom_roles_deleted"] = len(role_ids)

        conn.execute("DELETE FROM gradient_permissions WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM vote_log WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM user_votes WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM user_extra_votes WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM booster_roles WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM user_settings WHERE guild_id = ?", (guild_id,))
        for role_id in role_ids:
            conn.execute("DELETE FROM role_memberships WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM custom_roles WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM guild_config WHERE guild_id = ?", (guild_id,))

        # Leveling tables
        conn.execute("DELETE FROM lvl_config WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_users WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_boosters WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_booster_inv WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_level_roles WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_prestige_roles WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_blessings WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_bless_daily WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_vip_roles WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_discord_roles WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_reactions WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_vc_sessions WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_vc_time WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_votes WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_big_boosters WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_active_big_booster WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM lvl_boost_daily WHERE guild_id = ?", (guild_id,))

        # VC tables
        conn.execute("DELETE FROM vc_permissions WHERE channel_id IN (SELECT channel_id FROM vc_channels WHERE guild_id = ?)", (guild_id,))
        conn.execute("DELETE FROM vc_deafened WHERE channel_id IN (SELECT channel_id FROM vc_channels WHERE guild_id = ?)", (guild_id,))
        conn.execute("DELETE FROM vc_muted WHERE channel_id IN (SELECT channel_id FROM vc_channels WHERE guild_id = ?)", (guild_id,))
        conn.execute("DELETE FROM vc_channels WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM vc_settings WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM vc_admin_perms WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM vc_hub WHERE guild_id = ?", (guild_id,))

        conn.commit()

    # Delete custom Discord roles
    if guild:
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role:
                try:
                    await role.delete(reason="Server cache cleared by admin")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                await asyncio.sleep(0.3)

    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# Clear Cache Confirm View (uses the fixed clear_server_data)
# ═══════════════════════════════════════════════════════════════════════════════

class ClearCacheConfirmView(discord.ui.View):
    def __init__(self, guild: discord.Guild, invoker: discord.Member):
        super().__init__(timeout=30)
        self.guild = guild
        self.invoker = invoker

    @discord.ui.button(label="Yes, delete everything", style=discord.ButtonStyle.danger, emoji=EMOJI_DELETE)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJI_ERROR} **Only the admin who triggered this can confirm.**", color=discord.Color.red()),
                ephemeral=True
            )
            return

        self.stop()
        for child in self.children:
            child.disabled = True

        steps = [
            (EMOJI_DELETE, "Clearing custom roles..."),
            (EMOJI_DELETE, "Deleting voice channels..."),
            (EMOJI_DELETE, "Clearing database records..."),
        ]

        embed = discord.Embed(
            title=f"{EMOJI_DELETE} **Clearing Server Data**",
            description=f"{EMOJI_DELETE} Starting...",
            color=discord.Color.red()
        )
        embed.set_author(name=self.invoker.display_name, icon_url=self.invoker.avatar.url if self.invoker.avatar else None)
        await interaction.response.edit_message(embed=embed, view=self)

        for emoji, label in steps:
            embed.description = f"{emoji} **{label}**"
            await interaction.edit_original_response(embed=embed)
            await asyncio.sleep(0.8)

        summary = await clear_server_data(self.guild.id, self.guild)

        result_embed = discord.Embed(
            title=f"{EMOJI_SUCCESS} **Cache Cleared**",
            description=(
                f"All server data for **{self.guild.name}** has been wiped.\n\n"
                f"**Deleted:**\n"
                f"• {summary['custom_roles_deleted']} custom role(s)\n"
                f"• {summary['voice_channels_deleted']} voice channel(s)\n"
                f"• Hub channel: {'✅' if summary['hub_channel_deleted'] else '❌ (already missing)'}\n"
            ),
            color=discord.Color.green()
        )
        if summary["errors"]:
            result_embed.add_field(
                name=f"{EMOJI_WARNING} Errors encountered",
                value="\n".join(summary["errors"][:5]),
                inline=False
            )
        result_embed.set_footer(text="The bot is now fresh for this server. Run /setup to reconfigure.")

        await interaction.edit_original_response(embed=result_embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJI_ERROR} **Only the admin who triggered this can cancel.**", color=discord.Color.red()),
                ephemeral=True
            )
            return
        self.stop()
        await _show_setup_embed(interaction, edit=True)

    async def on_timeout(self):
        pass
# ---------- Admin Boost Panel ----------
class BoostAdminView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild

    @discord.ui.button(label="Add Booster Role", style=discord.ButtonStyle.success, emoji=EMOJI_ADD)
    async def add_booster(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="Add Booster Role")
        role_id_input = discord.ui.TextInput(label="Role ID", placeholder="Enter the role ID")
        extra_input = discord.ui.TextInput(label="Extra Votes", placeholder="Number of extra votes per day", default="1")
        modal.add_item(role_id_input)
        modal.add_item(extra_input)
        async def on_submit(modal_interaction):
            try:
                role_id = int(role_id_input.value)
                extra = int(extra_input.value)
                role = self.guild.get_role(role_id)
                if not role:
                    embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
                    embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                    await send_then_delete(modal_interaction, embed)
                    return
                await add_booster_role(self.guild.id, role_id, extra)
                embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{role.mention}** now grants **{extra}** extra votes per day.", color=discord.Color.green())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
            except ValueError:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid input.**", color=discord.Color.red())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Booster Role", style=discord.ButtonStyle.primary, emoji=EMOJI_GEAR)
    async def edit_booster(self, interaction: discord.Interaction, button: discord.ui.Button):
        boosters = await get_booster_roles(self.guild.id)
        if not boosters:
            embed = discord.Embed(description=f"{EMOJI_WARNING} **No booster roles configured.**", color=discord.Color.orange())
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await send_then_delete(interaction, embed)
            return
        options = []
        for role_id, extra in boosters:
            role = self.guild.get_role(role_id)
            if role:
                options.append(discord.SelectOption(label=role.name, value=str(role_id), description=f"{extra} extra votes"))
        if not options:
            embed = discord.Embed(description=f"{EMOJI_WARNING} **No valid booster roles found.**", color=discord.Color.orange())
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await send_then_delete(interaction, embed)
            return
        select = discord.ui.Select(placeholder="Select a booster role to edit...", options=options, min_values=1, max_values=1)
        async def select_callback(select_interaction):
            role_id = int(select.values[0])
            modal = discord.ui.Modal(title="Edit Booster Role")
            extra_input = discord.ui.TextInput(label="New Extra Votes", placeholder="Number of extra votes per day")
            modal.add_item(extra_input)
            async def on_submit(modal_interaction):
                try:
                    new_extra = int(extra_input.value)
                    await add_booster_role(self.guild.id, role_id, new_extra)
                    role = self.guild.get_role(role_id)
                    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{role.mention}** now grants **{new_extra}** extra votes.", color=discord.Color.green())
                    embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                    await send_then_delete(modal_interaction, embed)
                except ValueError:
                    embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid number.**", color=discord.Color.red())
                    embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                    await send_then_delete(modal_interaction, embed)
            modal.on_submit = on_submit
            await select_interaction.response.send_modal(modal)
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select a booster role to edit:", view=view, ephemeral=True)

    @discord.ui.button(label="Set Daily Limit", style=discord.ButtonStyle.secondary, emoji=EMOJI_PIN)
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="Daily Vote Limit")
        limit_input = discord.ui.TextInput(label="Base Votes per user", placeholder="Default: 1")
        modal.add_item(limit_input)
        async def on_submit(modal_interaction):
            try:
                limit = int(limit_input.value)
                if limit < 0:
                    raise ValueError
                await set_daily_vote_limit(self.guild.id, limit)
                embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Daily vote limit set to {limit}.**", color=discord.Color.green())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
            except ValueError:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid number.**", color=discord.Color.red())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set User Daily Limit", style=discord.ButtonStyle.primary, emoji=EMOJI_USER)
    async def set_user_daily_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="Set User Daily Limit")
        user_id_input = discord.ui.TextInput(label="User ID", placeholder="Discord user ID")
        limit_input = discord.ui.TextInput(label="Daily Limit", placeholder="Number of daily votes (0 to remove override)")
        modal.add_item(user_id_input)
        modal.add_item(limit_input)
        async def on_submit(modal_interaction):
            try:
                user_id = int(user_id_input.value)
                limit = int(limit_input.value) if limit_input.value else None
                user = self.guild.get_member(user_id)
                if not user:
                    embed = discord.Embed(description=f"{EMOJI_ERROR} **User not found.**", color=discord.Color.red())
                    embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                    await send_then_delete(modal_interaction, embed)
                    return
                await set_user_daily_limit_override(user_id, self.guild.id, limit)
                if limit is not None:
                    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{user.mention}** now gets **{limit}** daily votes (override).", color=discord.Color.green())
                else:
                    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{user.mention}** daily limit override removed.", color=discord.Color.green())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
            except ValueError:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid input.**", color=discord.Color.red())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Extra Boost", style=discord.ButtonStyle.success, emoji=EMOJI_ADD)
    async def add_extra_boost(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="Add Extra Boost")
        user_id_input = discord.ui.TextInput(label="User ID", placeholder="Discord user ID")
        amount_input = discord.ui.TextInput(label="Extra Boosts", placeholder="Number of extra boosts to add")
        modal.add_item(user_id_input)
        modal.add_item(amount_input)
        async def on_submit(modal_interaction):
            try:
                user_id = int(user_id_input.value)
                amount = int(amount_input.value)
                if amount <= 0:
                    raise ValueError
                user = self.guild.get_member(user_id)
                if not user:
                    embed = discord.Embed(description=f"{EMOJI_ERROR} **User not found.**", color=discord.Color.red())
                    embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                    await send_then_delete(modal_interaction, embed)
                    return
                await add_user_extra_votes(user_id, self.guild.id, amount)
                embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Added {amount} extra boost(s) to {user.mention}.**", color=discord.Color.green())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
            except ValueError:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid input.**", color=discord.Color.red())
                embed.set_author(name=modal_interaction.user.display_name, icon_url=modal_interaction.user.avatar.url if modal_interaction.user.avatar else None)
                await send_then_delete(modal_interaction, embed)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Weekly Winner Channel", style=discord.ButtonStyle.primary, emoji="<a:Trophy:1007651471002701834>", row=2)
    async def winner_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ensure_lvl_config(self.guild.id)
        cfg = get_lvl_config(self.guild.id)
        current_ch = self.guild.get_channel(cfg["winner_channel_id"]) if cfg.get("winner_channel_id") else None
        current_txt = f"Currently set to {current_ch.mention}" if current_ch else "Not set — winner embed will be sent as a DM."

        ch_select = discord.ui.ChannelSelect(
            placeholder="Select announcement channel...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

        async def ch_callback(sel_interaction: discord.Interaction):
            ch = ch_select.values[0]
            with get_db() as conn:
                conn.execute(
                    "UPDATE lvl_config SET winner_channel_id=? WHERE guild_id=?",
                    (ch.id, self.guild.id)
                )
                conn.commit()
            embed = discord.Embed(
                description=(
                    f"<a:Trophy:1007651471002701834> **Weekly winner announcements will be posted in {ch.mention}.**\n\n"
                    f"Every Monday at midnight UTC the bot will automatically announce the top-boosted role owner "
                    f"and grant them gradient permission."
                ),
                color=discord.Color.green()
            )
            embed.set_author(name=sel_interaction.user.display_name, icon_url=sel_interaction.user.avatar.url if sel_interaction.user.avatar else None)
            await sel_interaction.response.edit_message(embed=embed, view=None)

        ch_select.callback = ch_callback

        clear_btn = discord.ui.Button(label="Clear Channel (use DM)", style=discord.ButtonStyle.danger, emoji=EMOJI_DELETE)

        async def clear_cb(cl_interaction: discord.Interaction):
            with get_db() as conn:
                conn.execute("UPDATE lvl_config SET winner_channel_id=NULL WHERE guild_id=?", (self.guild.id,))
                conn.commit()
            embed = discord.Embed(
                description=f"{EMOJI_SUCCESS} **Winner channel cleared.** The bot will DM the winner instead.",
                color=discord.Color.orange()
            )
            embed.set_author(name=cl_interaction.user.display_name, icon_url=cl_interaction.user.avatar.url if cl_interaction.user.avatar else None)
            await cl_interaction.response.edit_message(embed=embed, view=None)

        clear_btn.callback = clear_cb

        sel_view = discord.ui.View(timeout=60)
        sel_view.add_item(ch_select)
        sel_view.add_item(clear_btn)

        embed = discord.Embed(
            title="<a:Trophy:1007651471002701834> **Weekly Winner Announcement Channel**",
            description=(
                f"{current_txt}\n\n"
                f"Select a channel below where the weekly boost ranking winner will be announced every Monday. "
                f"The bot will post the congratulations embed and ping the winner there."
            ),
            color=discord.Color.gold()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.response.send_message(embed=embed, view=sel_view, ephemeral=True)


# ---------- Trigger Role Select UI ----------
class TriggerRoleSelectView(DisableOnTimeoutView):
    def __init__(self, guild_id: int, guild: discord.Guild):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.guild = guild

        role_select = discord.ui.RoleSelect(
            placeholder="Select a role to set as trigger role...",
            min_values=1,
            max_values=1
        )

        async def role_select_cb(interaction: discord.Interaction):
            role = role_select.values[0]
            # Defer immediately — set_trigger_role_id can take a long time if it
            # needs to create roles for existing members (asyncio.sleep loops).
            # Without defer, the 3-second interaction window expires and we get 10062.
            await interaction.response.defer()
            await set_trigger_role_id(self.guild_id, role.id, interaction.guild)
            embed = discord.Embed(
                title=f"{BTN_TRIGGER} **Set Trigger Role**",
                description=(
                    f"{EMOJI_SUCCESS} **Trigger role set to {role.mention}.**\n"
                    f"Members who receive this role will automatically get a custom role.\n\n"
                    f"Click **Clear Trigger Role** to remove it."
                ),
                color=discord.Color.green()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await interaction.edit_original_response(embed=embed, view=self)

        role_select.callback = role_select_cb
        self.add_item(role_select)

        clear_btn = discord.ui.Button(label="Clear Trigger Role", style=discord.ButtonStyle.danger)

        async def clear_cb(interaction: discord.Interaction):
            await set_trigger_role_id(self.guild_id, None, interaction.guild)
            embed = discord.Embed(
                title=f"{BTN_TRIGGER} **Set Trigger Role**",
                description=(
                    f"{EMOJI_SUCCESS} **Trigger role removed.**\n\n"
                    f"Select a role below to set a new trigger role."
                ),
                color=discord.Color.orange()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await interaction.response.edit_message(embed=embed, view=self)

        clear_btn.callback = clear_cb
        self.add_item(clear_btn)

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)

        async def back_cb(interaction: discord.Interaction):
            await _show_setup_embed(interaction, edit=True)

        back_btn.callback = back_cb
        self.add_item(back_btn)


# ---------- Whitelist Select UI ----------
class WhitelistSelectView(DisableOnTimeoutView):
    def __init__(self, guild_id: int, whitelist_column: str):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.whitelist_column = whitelist_column
        wl_label = "Role Add" if whitelist_column == "role_add" else "Role Remove"

        mentionable_select = discord.ui.MentionableSelect(
            placeholder="Select users or roles to whitelist...",
            min_values=1,
            max_values=10
        )

        async def select_cb(interaction: discord.Interaction):
            ids = [str(item.id) for item in mentionable_select.values]
            ids_str = ','.join(ids)
            col = f"{whitelist_column}_whitelist"
            with get_db() as conn:
                conn.execute(f"UPDATE guild_config SET {col} = ? WHERE guild_id = ?", (ids_str, self.guild_id))
                conn.commit()
            mentions = [item.mention for item in mentionable_select.values]
            embed = discord.Embed(
                title=f"{EMOJI_ADD} **Whitelist — {wl_label}**",
                description=(
                    f"{EMOJI_SUCCESS} **Whitelist updated.**\n"
                    f"Whitelisted: {', '.join(mentions)}\n\n"
                    f"Select again to replace, or click **Clear Whitelist** to remove all."
                ),
                color=discord.Color.green()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await interaction.response.edit_message(embed=embed, view=self)

        mentionable_select.callback = select_cb
        self.add_item(mentionable_select)

        clear_btn = discord.ui.Button(label="Clear Whitelist", style=discord.ButtonStyle.danger)

        async def clear_cb(interaction: discord.Interaction):
            col = f"{whitelist_column}_whitelist"
            with get_db() as conn:
                conn.execute(f"UPDATE guild_config SET {col} = ? WHERE guild_id = ?", ('', self.guild_id))
                conn.commit()
            embed = discord.Embed(
                title=f"{EMOJI_ADD} **Whitelist — {wl_label}**",
                description=(
                    f"{EMOJI_SUCCESS} **Whitelist cleared.**\n\n"
                    f"Select users or roles below to add new entries."
                ),
                color=discord.Color.orange()
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
            await interaction.response.edit_message(embed=embed, view=self)

        clear_btn.callback = clear_cb
        self.add_item(clear_btn)

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)

        async def back_cb(interaction: discord.Interaction):
            await _show_setup_embed(interaction, edit=True)

        back_btn.callback = back_cb
        self.add_item(back_btn)


# ---------- Expiry Background Task ----------
class RoleBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        super().__init__(command_prefix=self.get_prefix, intents=intents, help_command=None, case_insensitive=True)

    async def get_prefix(self, message: discord.Message):
        if not message.guild:
            return ["!", "."]
        with get_db() as conn:
            cur = conn.execute("SELECT prefix FROM guild_config WHERE guild_id = ?", (message.guild.id,))
            row = cur.fetchone()
        server_prefix = row[0] if row else "!"
        # Always keep "." as a permanent second prefix regardless of server setting
        return list({server_prefix, "."})

    async def setup_hook(self):
        await self.tree.sync()
        self.expiry_loop.start()
        self.weekly_winner_loop.start()

    async def on_ready(self):
        print(f"{EMOJI_SUCCESS} Logged in as {self.user} (ID: {self.user.id})")
        print(f"{EMOJI_INFO} Bot is ready!")
        for guild in self.guilds:
            tier = guild.premium_tier
            if tier >= 3:
                print(f"{EMOJI_SUCCESS} [{guild.name}] Boost Level {tier} — Role Style Color (gradient) is available.")
            else:
                print(f"{EMOJI_WARNING} [{guild.name}] Boost Level {tier} — Role Style Color requires Level 3 (currently locked).")

    @tasks.loop(hours=1)
    async def expiry_loop(self):
        now = datetime.now(timezone.utc)
        warning_threshold = now + timedelta(days=3)

        with get_db() as conn:
            # ── Phase 1: 3-day expiry warnings ──────────────────────────────
            cur = conn.execute(
                "SELECT user_id, role_id FROM role_memberships WHERE expires_at > ? AND expires_at <= ? AND warned_expiry = 0",
                (now, warning_threshold)
            )
            warn_rows = cur.fetchall()
            for user_id, role_id in warn_rows:
                cur2 = conn.execute("SELECT guild_id, owner_id FROM custom_roles WHERE role_id = ?", (role_id,))
                crow = cur2.fetchone()
                if not crow:
                    continue
                guild_id, owner_id = crow
                guild = self.get_guild(guild_id)
                if not guild:
                    continue
                role = guild.get_role(role_id)
                role_name = role.name if role else f"<deleted role {role_id}>"
                user = self.get_user(user_id) or await self.fetch_user(user_id)
                if user:
                    cur3 = conn.execute("SELECT expires_at FROM role_memberships WHERE user_id = ? AND role_id = ?", (user_id, role_id))
                    exp_row = cur3.fetchone()
                    if exp_row:
                        expires_ts = int(exp_row[0].timestamp()) if hasattr(exp_row[0], "timestamp") else int(datetime.fromisoformat(str(exp_row[0])).timestamp())
                        if owner_id == user_id:
                            embed = discord.Embed(
                                title=f"{EMOJI_WARNING} **Your custom role is expiring soon**",
                                description=(
                                    f"Your role **{role_name}** in **{guild.name}** expires <t:{expires_ts}:R>.\n\n"
                                    f"Once it expires, the role will be **permanently deleted** for all members. "
                                    f"Ask a server admin to extend it if needed."
                                ),
                                color=discord.Color.orange()
                            )
                        else:
                            embed = discord.Embed(
                                title=f"{EMOJI_WARNING} **Your role access is expiring soon**",
                                description=(
                                    f"Your membership in **{role_name}** in **{guild.name}** expires <t:{expires_ts}:R>.\n\n"
                                    f"After that you will lose access to the role."
                                ),
                                color=discord.Color.orange()
                            )
                        embed.set_footer(text="This is an automated notification.")
                        await try_dm(user, embed)
                conn.execute(
                    "UPDATE role_memberships SET warned_expiry = 1 WHERE user_id = ? AND role_id = ?",
                    (user_id, role_id)
                )

            # ── Phase 2: Handle expired memberships (consume stacks or delete) ────
            cur = conn.execute(
                "SELECT rm.user_id, rm.role_id, cr.stack_count, cr.guild_id, cr.owner_id "
                "FROM role_memberships rm JOIN custom_roles cr ON rm.role_id = cr.role_id "
                "WHERE rm.expires_at <= ?", (now,)
            )
            expired = cur.fetchall()
            for user_id, role_id, stack_count, guild_id, owner_id in expired:
                guild = self.get_guild(guild_id)
                if not guild:
                    continue
                role = guild.get_role(role_id)
                role_name = role.name if role else f"role {role_id}"

                if stack_count > 0 and owner_id == user_id:
                    # Consume one stacked credit — extend validity 30 days
                    new_expiry = now + timedelta(days=30)
                    conn.execute(
                        "UPDATE role_memberships SET expires_at = ?, warned_expiry = 0 WHERE user_id = ? AND role_id = ?",
                        (new_expiry, user_id, role_id)
                    )
                    conn.execute(
                        "UPDATE custom_roles SET stack_count = stack_count - 1 WHERE role_id = ?",
                        (role_id,)
                    )
                    # Notify owner that a credit was consumed
                    notify_user = self.get_user(user_id) or await self.fetch_user(user_id)
                    if notify_user:
                        notify_embed = discord.Embed(
                            title=f"{EMOJI_STACK} **Stacked credit consumed**",
                            description=(
                                f"Your role **{role_name}** in **{guild.name}** expired but a stacked credit was used.\n"
                                f"New expiry: <t:{int(new_expiry.timestamp())}:R> · Credits remaining: **{stack_count - 1}**"
                            ),
                            color=discord.Color.blue()
                        )
                        notify_embed.set_footer(text="This is an automated notification.")
                        await try_dm(notify_user, notify_embed)
                    continue  # Skip deletion — role is renewed

                # No credits left — remove role and delete if owner
                member = await get_or_fetch_member(guild, user_id)
                if member and role:
                    await member.remove_roles(role)

                user_obj = self.get_user(user_id) or await self.fetch_user(user_id)
                if user_obj:
                    if owner_id == user_id:
                        del_embed = discord.Embed(
                            title=f"{EMOJI_DELETE} **Your custom role has been deleted**",
                            description=(
                                f"Your role **{role_name}** in **{guild.name}** has expired and been permanently deleted.\n\n"
                                f"All members have lost access. Contact a server admin if you believe this is an error."
                            ),
                            color=discord.Color.red()
                        )
                    else:
                        del_embed = discord.Embed(
                            title=f"{EMOJI_DELETE} **Your role access has expired**",
                            description=f"Your membership in **{role_name}** in **{guild.name}** has expired and been removed.",
                            color=discord.Color.red()
                        )
                    del_embed.set_footer(text="This is an automated notification.")
                    await try_dm(user_obj, del_embed)

                conn.execute("DELETE FROM role_memberships WHERE user_id = ? AND role_id = ?", (user_id, role_id))

                if owner_id == user_id:
                    if role:
                        try:
                            await role.delete(reason="Role expired — no stacked credits remaining")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                    conn.execute("DELETE FROM custom_roles WHERE role_id = ?", (role_id,))

            conn.commit()

    @expiry_loop.before_loop
    async def before_expiry(self):
        await self.wait_until_ready()

    @tasks.loop(hours=1)
    async def weekly_winner_loop(self):
        now = datetime.now(timezone.utc)
        # Only fire on Monday (weekday=0) at hour 0 (midnight–1am UTC)
        if now.weekday() != 0 or now.hour != 0:
            return
        for guild in self.guilds:
            await announce_weekly_winner(guild, self)

    @weekly_winner_loop.before_loop
    async def before_winner_loop(self):
        await self.wait_until_ready()

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.author.id in upload_listeners and message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith('image/'):
                future = upload_listeners.pop(message.author.id)
                if not future.done():
                    future.set_result(message)
                return
        await self.process_commands(message)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        usage_map = {
            "boost":          "`!boost <@user> <quantity/all>`",
            "-boost":         "`!-boost <@user> <quantity/all>`",
            "testrole":       "`!testrole [image_url]`",
            "role add":       "`!role add <@user>`",
            "role remove":    "`!role remove <@user>`",
            "role give":      "`!role give <@user>`",
            "set name":       "`!set name <new name>`",
            "set color":      "`!set color <#hex>` — e.g. `#ff0000`",
            "set emoji":      "`!set emoji <emoji>`",
            "set icon":       "`!set icon` — attach an image to your message",
            "sys add boost":  "`!sys add boost <@role> <number>`",
            "sys add vote":   "`!sys add vote <@user> <number>`",
            "sys add extra":  "`!sys add extra <@user> <number>`",
            "sys role edit":  "`!sys role edit <@user>`",
            "sys role value": "`!sys role value <@user> <add/rm> <days>`",
        }
        if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument,
                               commands.UserNotFound, commands.MemberNotFound,
                               commands.RoleNotFound, commands.BadUnionArgument)):
            cmd = ctx.command
            if cmd:
                usage = usage_map.get(cmd.qualified_name)
                if usage:
                    embed = discord.Embed(
                        description=f"{EMOJI_ERROR} **Usage:** {usage}",
                        color=discord.Color.red()
                    )
                    await send_then_delete(ctx, embed, delay=10)
                    return
        elif isinstance(error, (commands.MissingPermissions, commands.CheckFailure)):
            embed = discord.Embed(
                description=f"{EMOJI_ERROR} **You don't have permission to use this command.**",
                color=discord.Color.red()
            )
            await send_then_delete(ctx, embed, delay=10)
            return
        elif isinstance(error, commands.CommandNotFound):
            return

bot = RoleBot()

# ---------- Events ----------
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # Server booster started — silently create custom role if they don't have one
    if before.premium_since is None and after.premium_since is not None:
        existing = await get_user_role_membership(after.id, after.guild.id)
        if not existing:
            await create_custom_role_for_user(after, after.guild, after.guild.me)

    trigger_role_id = await get_trigger_role_id(after.guild.id)
    if not trigger_role_id:
        return
    before_roles = set(before.roles)
    after_roles = set(after.roles)
    gained_roles = after_roles - before_roles
    trigger_role = after.guild.get_role(trigger_role_id)
    if trigger_role and trigger_role in gained_roles:
        existing = await get_user_role_membership(after.id, after.guild.id)
        if not existing:
            await create_custom_role_for_user(after, after.guild, after.guild.me)

@bot.event
async def on_member_join(member: discord.Member):
    gradient_available = can_use_gradient(member.guild)
    if not gradient_available:
        print(f"{EMOJI_WARNING} [{member.guild.name}] Role Style Color locked (Boost Level {member.guild.premium_tier}/3) — member {member} joined.")
    trigger_role_id = await get_trigger_role_id(member.guild.id)
    if not trigger_role_id:
        return
    trigger_role = member.guild.get_role(trigger_role_id)
    if trigger_role and trigger_role in member.roles:
        existing = await get_user_role_membership(member.id, member.guild.id)
        if not existing:
            await create_custom_role_for_user(member, member.guild, member.guild.me)

# ---------- Permission Helpers ----------
async def is_admin_or_whitelisted(user: discord.Member, action: str, guild: discord.Guild) -> bool:
    if user.guild_permissions.administrator:
        return True
    with get_db() as conn:
        cur = conn.execute("SELECT role_add_whitelist, role_remove_whitelist FROM guild_config WHERE guild_id = ?", (guild.id,))
        row = cur.fetchone()
    if not row:
        return False
    add_wl = row[0] or ""
    remove_wl = row[1] or ""
    if action == "role_add":
        combined = add_wl
    elif action == "role_remove":
        combined = remove_wl
    else:
        combined = add_wl + "," + remove_wl
    allowed_ids = [int(x.strip()) for x in combined.split(',') if x.strip().isdigit()]
    if user.id in allowed_ids:
        return True
    return any(role.id in allowed_ids for role in user.roles)

async def get_user_role_membership(user_id: int, guild_id: int) -> Optional[Tuple[int, int, datetime, int]]:
    with get_db() as conn:
        cur = conn.execute("""
            SELECT cr.role_id, cr.stack_count, rm.expires_at, cr.owner_id
            FROM role_memberships rm
            JOIN custom_roles cr ON rm.role_id = cr.role_id
            WHERE rm.user_id = ? AND cr.guild_id = ?
        """, (user_id, guild_id))
        row = cur.fetchone()
        if row:
            return (row[0], row[1], row[2], row[3])
        return None

async def get_owned_role(user_id: int, guild_id: int) -> Optional[Tuple[int, int, int]]:
    with get_db() as conn:
        cur = conn.execute("SELECT role_id, color, max_recipients FROM custom_roles WHERE guild_id = ? AND owner_id = ?", (guild_id, user_id))
        return cur.fetchone()

# ---------- Core Logic ----------
async def role_info_logic(ctx_or_inter, user: discord.Member, guild: discord.Guild):
    owned = await get_owned_role(user.id, guild.id)
    if owned:
        role_id, color_int, _ = owned
        role = guild.get_role(role_id)
        if not role:
            embed = discord.Embed(description=f"{EMOJI_WARNING} **Role not found.** It may have been deleted.", color=discord.Color.red())
            if isinstance(ctx_or_inter, discord.Interaction):
                await ctx_or_inter.response.send_message(embed=embed)
            else:
                await ctx_or_inter.send(embed=embed)
            return
        with get_db() as conn:
            cur = conn.execute("SELECT name, icon_url FROM custom_roles WHERE role_id = ?", (role_id,))
            row = cur.fetchone()
            name, icon_url = row if row else ("Unknown", None)
        embed = discord.Embed(title="Role Information", color=role.color)
        embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
        if icon_url:
            embed.set_thumbnail(url=icon_url)
        embed.add_field(name=f"{EMOJI_MEMO} Name", value=f"`{name}`", inline=False)
        embed.add_field(name=f"{EMOJI_COLOR} Color", value=f"`{int_to_hex(color_int)}`", inline=False)
        view = RoleInfoView(role, role_id, user.id, guild, None)
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(embed=embed, view=view)
            msg = await ctx_or_inter.original_response()
            view.original_message = msg
        else:
            sent_msg = await ctx_or_inter.send(embed=embed, view=view)
            view.original_message = sent_msg
    else:
        embed = discord.Embed(description=f"{EMOJI_WARNING} **You don't own any custom role.**", color=discord.Color.orange())
        embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(embed=embed)
        else:
            await ctx_or_inter.send(embed=embed)

async def role_give_logic(ctx_or_inter, target: discord.User, guild: discord.Guild, author: discord.Member):
    if target == author:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You cannot give the role to yourself.**", color=discord.Color.red())
        await send_then_delete(ctx_or_inter, embed)
        return
    owned = await get_owned_role(author.id, guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't own any role to give.**", color=discord.Color.red())
        await send_then_delete(ctx_or_inter, embed)
        return
    role_id, _, max_rec = owned
    role = guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role no longer exists.**", color=discord.Color.red())
        await send_then_delete(ctx_or_inter, embed)
        return
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM role_memberships WHERE role_id = ? AND user_id != ?", (role_id, author.id))
        recipient_count = cur.fetchone()[0]
    if recipient_count >= max_rec:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **This role has already been given to {max_rec} users (maximum).**", color=discord.Color.red())
        await send_then_delete(ctx_or_inter, embed)
        return
    with get_db() as conn:
        cur = conn.execute("SELECT 1 FROM role_memberships WHERE role_id = ? AND user_id = ?", (role_id, target.id))
        if cur.fetchone():
            embed = discord.Embed(description=f"{EMOJI_ERROR} **{target.display_name} already has this role.**", color=discord.Color.red())
            await send_then_delete(ctx_or_inter, embed)
            return
    granted_at = datetime.now(timezone.utc)
    expires_at = granted_at + timedelta(days=30)
    with get_db() as conn:
        conn.execute("INSERT INTO role_memberships (user_id, role_id, granted_at, expires_at, granted_by) VALUES (?, ?, ?, ?, ?)",
                     (target.id, role_id, granted_at, expires_at, author.id))
        conn.commit()
    member = await get_or_fetch_member(guild, target.id)
    if member:
        await member.add_roles(role)
        embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Your role was given to {target.mention}**", color=discord.Color.green())
        await send_then_delete(ctx_or_inter, embed)
    else:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Could not find that member.**", color=discord.Color.red())
        await send_then_delete(ctx_or_inter, embed)

async def role_add_logic(ctx_or_inter, user: discord.User, guild: discord.Guild, author: discord.Member):
    existing = await get_user_role_membership(user.id, guild.id)
    if existing:
        role_id, stack_count, expires_at, owner_id = existing
        role = guild.get_role(role_id)
        if not role:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
            await send_then_delete(ctx_or_inter, embed)
            return
        # Bank a stacked credit — doesn't touch expires_at, just increments stack_count
        with get_db() as conn:
            conn.execute("UPDATE custom_roles SET stack_count = stack_count + 1 WHERE role_id = ?", (role_id,))
            conn.commit()
        embed = discord.Embed(
            description=(
                f"{EMOJI_SUCCESS} **Stacked credit added for {user.mention}.**\n"
                f"Current expiry: <t:{int(expires_at.timestamp())}:R> · "
                f"Credits banked: **{stack_count + 1}**"
            ),
            color=discord.Color.green()
        )
        await send_then_delete(ctx_or_inter, embed)
        return
    role_name = f"Custom-{user.name}"
    try:
        new_role = await guild.create_role(name=role_name, color=discord.Color(0x99aab5), reason="Custom role creation")
    except discord.Forbidden:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Bot lacks permission to create roles.**", color=discord.Color.red())
        await send_then_delete(ctx_or_inter, embed)
        return
    default_icon_url = emoji_to_url(DEFAULT_THUMBNAIL)
    with get_db() as conn:
        conn.execute("INSERT INTO custom_roles (role_id, guild_id, owner_id, name, color, icon_url, max_recipients, stack_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (new_role.id, guild.id, user.id, role_name, 0x99aab5, default_icon_url, 50, 0))
        granted_at = datetime.now(timezone.utc)
        expires_at = granted_at + timedelta(days=30)
        conn.execute("INSERT INTO role_memberships (user_id, role_id, granted_at, expires_at, granted_by) VALUES (?, ?, ?, ?, ?)",
                     (user.id, new_role.id, granted_at, expires_at, author.id))
        conn.commit()
    member = await get_or_fetch_member(guild, user.id)
    if member:
        await member.add_roles(new_role)
        embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Created role {new_role.name} for {user.mention}.** Expires <t:{int(expires_at.timestamp())}:R>.", color=discord.Color.green())
        await send_then_delete(ctx_or_inter, embed)
    else:
        embed = discord.Embed(description=f"{EMOJI_WARNING} **Role created but user not found.**", color=discord.Color.yellow())
        await send_then_delete(ctx_or_inter, embed)
    await ensure_role_highlighted(new_role, guild)

async def role_remove_logic(ctx_or_inter, user: discord.User, guild: discord.Guild):
    with get_db() as conn:
        cur = conn.execute("""
            SELECT cr.role_id FROM custom_roles cr
            JOIN role_memberships rm ON cr.role_id = rm.role_id
            WHERE cr.guild_id = ? AND rm.user_id = ?
        """, (guild.id, user.id))
        role_ids = [row[0] for row in cur.fetchall()]
    if not role_ids:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{user.mention} does not have any custom role.**", color=discord.Color.red())
        await send_then_delete(ctx_or_inter, embed)
        return
    for role_id in role_ids:
        role = guild.get_role(role_id)
        member = await get_or_fetch_member(guild, user.id)
        if member and role:
            await member.remove_roles(role)
        with get_db() as conn:
            conn.execute("DELETE FROM role_memberships WHERE user_id = ? AND role_id = ?", (user.id, role_id))
            cur2 = conn.execute("SELECT owner_id FROM custom_roles WHERE role_id = ?", (role_id,))
            owner_row = cur2.fetchone()
            if owner_row and owner_row[0] == user.id and role:
                await role.delete()
                conn.execute("DELETE FROM custom_roles WHERE role_id = ?", (role_id,))
            conn.commit()
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Removed custom role(s) from {user.mention}.**", color=discord.Color.green())
    await send_then_delete(ctx_or_inter, embed)

async def role_date_logic(ctx_or_inter, user: discord.User, guild: discord.Guild):
    EMOJI_ROLE = "<:role:1506446184246542457>"
    membership = await get_user_role_membership(user.id, guild.id)
    now = datetime.now(timezone.utc)

    # No DB record at all
    if not membership:
        embed = discord.Embed(
            description=f"{EMOJI_WARNING} **{user.mention} doesn't have a custom role.**",
            color=discord.Color.orange()
        )
        embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
        await send_then_delete(ctx_or_inter, embed)
        return

    role_id, stack_count, expires_at, owner_id = membership
    role = guild.get_role(role_id)
    remaining = expires_at - now

    # Expired and no credits left (expiry loop hasn't run yet)
    if remaining.total_seconds() <= 0 and stack_count == 0:
        embed = discord.Embed(
            description=f"{EMOJI_WARNING} **{user.mention} doesn't have a custom role.**",
            color=discord.Color.orange()
        )
        embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
        await send_then_delete(ctx_or_inter, embed)
        return

    # Expired but has credits — expiry loop will renew it; show pending state
    if remaining.total_seconds() <= 0 and stack_count > 0:
        embed = discord.Embed(
            title=f"{EMOJI_PERFORMINGARTS} **Role Validity**",
            description=f"{EMOJI_STACK} **Validity expired — {stack_count} credit(s) will auto-renew for 30 days each.**",
            color=discord.Color.orange()
        )
        embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
        if role:
            embed.add_field(name=f"{EMOJI_ROLE} **Role**", value=role.mention, inline=False)
        embed.add_field(name=f"{EMOJI_STACK} **Credits Remaining**", value=str(stack_count), inline=False)
        if isinstance(ctx_or_inter, discord.Interaction):
            if not ctx_or_inter.response.is_done():
                await ctx_or_inter.response.send_message(embed=embed)
            else:
                await ctx_or_inter.followup.send(embed=embed)
        else:
            await ctx_or_inter.send(embed=embed)
        return

    if not role:
        embed = discord.Embed(
            description=f"{EMOJI_WARNING} **{user.mention} doesn't have a custom role.**",
            color=discord.Color.orange()
        )
        embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
        await send_then_delete(ctx_or_inter, embed)
        return

    days = remaining.days
    hours = remaining.seconds // 3600
    minutes = (remaining.seconds % 3600) // 60
    remaining_text = f"{days}d {hours}h {minutes}m"

    # Total effective days including banked credits
    total_days = days + (stack_count * 30)

    embed = discord.Embed(title=f"{EMOJI_PERFORMINGARTS} **Role Validity**", color=role.color)
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
    embed.add_field(name=f"{EMOJI_USER} **User**", value=user.mention, inline=False)
    embed.add_field(name=f"{EMOJI_ROLE} **Role**", value=role.mention, inline=False)
    embed.add_field(name=f"{EMOJI_INFO} **Expires**", value=f"<t:{int(expires_at.timestamp())}:R> ({remaining_text})", inline=False)
    embed.add_field(name=f"{EMOJI_STACK} **Stacked Credits**", value=f"**{stack_count}** credit(s) banked (~{total_days} days total)", inline=False)
    if isinstance(ctx_or_inter, discord.Interaction):
        if not ctx_or_inter.response.is_done():
            await ctx_or_inter.response.send_message(embed=embed)
        else:
            await ctx_or_inter.followup.send(embed=embed)
    else:
        await ctx_or_inter.send(embed=embed)

# ---------- Test Role Icon Command ----------
DISCORD_ROLE_ICON_MAX_BYTES = 256 * 1024  # 256 KB

@bot.group(name="test", invoke_without_command=True)
async def test_group(ctx: commands.Context):
    pass


@test_group.command(name="winner")
@commands.has_permissions(administrator=True)
async def cmd_test_winner(ctx: commands.Context):
    now = datetime.now(timezone.utc)
    days_ahead = (7 - now.weekday()) % 7 or 7
    next_reset = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
    reset_ts = int(next_reset.timestamp())
    await grant_gradient_permission(ctx.author.id, ctx.guild.id)
    embed = build_winner_embed(ctx.author, reset_ts)
    await ctx.send(content=ctx.author.mention, embed=embed)


@bot.command(name="testrole")
async def testrole_command(ctx: commands.Context, image_url: str = None):
    guild = ctx.guild
    lines = []
    all_ok = True

    # ── 1. User owns a custom role ──────────────────────────────────────────
    owned = await get_owned_role(ctx.author.id, guild.id)
    if not owned:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **You don't own a custom role in this server.**",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    role_id, _, _ = owned
    role = guild.get_role(role_id)
    if not role:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Your custom role exists in the database but not on Discord. It may have been manually deleted.**",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    lines.append(f"{EMOJI_SUCCESS} **You own a custom role:** {role.mention}")

    # ── 2. Server boost level ───────────────────────────────────────────────
    tier = guild.premium_tier
    if tier < 2:
        lines.append(f"{EMOJI_ERROR} **Server Boost Level:** {tier} — *Role icons require Level 2. Your server needs {2 - tier} more boost tier(s).*")
        all_ok = False
    else:
        lines.append(f"{EMOJI_SUCCESS} **Server Boost Level:** {tier} ✓ (Level 2+ required)")

    # ── 3. Bot has Manage Roles permission ──────────────────────────────────
    if not guild.me.guild_permissions.manage_roles:
        lines.append(f"{EMOJI_ERROR} **Bot permission:** Missing `Manage Roles` — grant it in Server Settings → Roles → Bot.")
        all_ok = False
    else:
        lines.append(f"{EMOJI_SUCCESS} **Bot permission:** `Manage Roles` ✓")

    # ── 4. Bot role hierarchy vs custom role ────────────────────────────────
    bot_top = guild.me.top_role
    if bot_top.position <= role.position:
        lines.append(
            f"{EMOJI_ERROR} **Role hierarchy:** Bot's highest role **{bot_top.mention}** (pos {bot_top.position}) is not above "
            f"**{role.mention}** (pos {role.position}). "
            f"Go to Server Settings → Roles and drag the bot's role higher."
        )
        all_ok = False
    else:
        lines.append(f"{EMOJI_SUCCESS} **Role hierarchy:** Bot role is above {role.mention} ✓")

    # ── 5. Image check (URL arg or attached file) ───────────────────────────
    attachment_url = image_url
    if not attachment_url and ctx.message.attachments:
        attachment_url = ctx.message.attachments[0].url

    if attachment_url:
        lines.append("")
        lines.append(f"**— Image Check —**")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment_url) as resp:
                    if resp.status != 200:
                        lines.append(f"{EMOJI_ERROR} **URL unreachable:** HTTP {resp.status} — check the link is publicly accessible.")
                        all_ok = False
                    else:
                        content_type = resp.content_type or ""
                        ALLOWED_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
                        if not content_type.startswith("image/"):
                            lines.append(f"{EMOJI_ERROR} **Not an image:** Content-Type is `{content_type}`. Must be PNG, JPEG, GIF, or WebP.")
                            all_ok = False
                        elif content_type not in ALLOWED_TYPES:
                            lines.append(f"{EMOJI_ERROR} **Unsupported format:** `{content_type}`. Discord only accepts PNG, JPEG, GIF, or WebP for role icons.")
                            all_ok = False
                        else:
                            lines.append(f"{EMOJI_SUCCESS} **Format:** `{content_type}` ✓")

                        img_data = await resp.read()
                        size_kb = len(img_data) / 1024
                        if len(img_data) > DISCORD_ROLE_ICON_MAX_BYTES:
                            lines.append(f"{EMOJI_ERROR} **File size:** {size_kb:.1f} KB — exceeds Discord's 256 KB limit for role icons. Compress the image.")
                            all_ok = False
                        else:
                            lines.append(f"{EMOJI_SUCCESS} **File size:** {size_kb:.1f} KB / 256 KB max ✓")

                        if all_ok and content_type in ALLOWED_TYPES and len(img_data) <= DISCORD_ROLE_ICON_MAX_BYTES:
                            try:
                                await role.edit(icon=img_data, reason="testrole icon check")
                                lines.append(f"{EMOJI_SUCCESS} **Live test:** Icon applied to {role.mention} successfully ✓")
                            except discord.Forbidden:
                                lines.append(f"{EMOJI_ERROR} **Live test failed:** Discord rejected the edit — double-check bot permissions and hierarchy.")
                                all_ok = False
                            except discord.HTTPException as e:
                                lines.append(f"{EMOJI_ERROR} **Live test failed:** Discord returned an error — `{e.text}`")
                                all_ok = False
        except Exception as e:
            lines.append(f"{EMOJI_ERROR} **Could not fetch image:** `{e}`")
            all_ok = False
    else:
        lines.append("")
        lines.append(f"{EMOJI_INFO} *No image provided — add a URL or attachment to also test the image. e.g. `!testrole https://...`*")

    # ── Summary ─────────────────────────────────────────────────────────────
    lines.append("")
    if all_ok:
        lines.append(f"{EMOJI_SUCCESS} **All checks passed — role icon will apply successfully.**")
        color = discord.Color.green()
    else:
        lines.append(f"{EMOJI_ERROR} **One or more checks failed — fix the issues above before setting an icon.**")
        color = discord.Color.red()

    embed = discord.Embed(
        title=f"{EMOJI_GEAR} **Role Icon Test**",
        description="\n".join(lines),
        color=color
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)


# ---------- Boost Command ----------
@bot.command(name="boost")
async def boost_command(ctx: commands.Context, target: str = None, amount: str = None):
    if target is None or amount is None:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!boost <@user> <quantity/all>`\nExample: `!boost @username 1` or `!boost @username all`", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return

    user_id = None
    cleaned = target.strip('<@!>')
    if cleaned.isdigit():
        user_id = int(cleaned)
    else:
        member = discord.utils.get(ctx.guild.members, name=target)
        if member:
            user_id = member.id
    if not user_id:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid user.** Please mention a user (e.g., `@username`) or use their ID.", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    member = ctx.guild.get_member(user_id)
    if not member:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **User not found in this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    owned = await get_owned_role(user_id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{member.display_name} does not own a custom role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found. It may have been deleted.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    daily_rem = await get_daily_votes_remaining(ctx.author.id, ctx.guild.id)
    if daily_rem == -1:
        total_daily = await get_user_total_votes(ctx.author, ctx.guild.id)
        await reset_daily_votes(ctx.author.id, ctx.guild.id, total_daily)
        daily_rem = total_daily
    extra_rem = await get_user_extra_votes(ctx.author.id, ctx.guild.id)

    if amount.lower() == "all":
        # ── "all": spend daily first (no confirm), then ask for extra ──────
        if daily_rem == 0 and extra_rem == 0:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **You have no boosts left.**", color=discord.Color.red())
            await send_then_delete(ctx, embed)
            return

        if daily_rem == 0:
            # No daily left — only extra; ask confirmation
            view = BoostConfirmView(ctx.author, role, extra_rem, 0, extra_rem, ctx)
            embed = discord.Embed(
                description=f"{EMOJI_WARNING} **Your daily boosts are over.**\nYou have **{extra_rem}** extra boost(s). Use all on {role.mention}?",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed, view=view)
            return

        # Spend all daily boosts immediately (no confirmation needed)
        success, daily_used, _ = await use_vote(ctx.author, ctx.guild.id, daily_rem)
        if not success:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed to use votes.**", color=discord.Color.red())
            await send_then_delete(ctx, embed)
            return
        await add_vote_to_role(role.id, ctx.guild.id, ctx.author.id, daily_rem)
        await create_boost_notification(user_id, ctx.guild.id, role.id, ctx.author.id, daily_rem)

        # Check remaining extra and ask confirmation if any
        extra_now = await get_user_extra_votes(ctx.author.id, ctx.guild.id)
        if extra_now > 0:
            view = BoostConfirmView(ctx.author, role, extra_now, 0, extra_now, ctx)
            embed = discord.Embed(
                description=f"{EMOJI_BOOSTED} **Used {daily_rem} daily boost(s) on {role.mention}!**\n\n"
                            f"{EMOJI_WARNING} You also have **{extra_now}** extra boost(s). Use them too?",
                color=discord.Color.orange()
            )
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            await ctx.send(embed=embed, view=view)
        else:
            embed = discord.Embed(
                description=f"{EMOJI_BOOSTED} **You boosted {role.mention} (owned by {member.mention}) with {daily_rem} vote(s)!**\nRemaining daily: **0**, extra: **0**",
                color=discord.Color.green()
            )
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            await send_then_delete(ctx, embed)
    else:
        # ── Specific number ────────────────────────────────────────────────
        try:
            votes = int(amount)
            if votes <= 0:
                raise ValueError
        except ValueError:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid amount.** Use a positive number or `all`.", color=discord.Color.red())
            await send_then_delete(ctx, embed)
            return

        total_available = daily_rem + extra_rem
        if total_available < votes:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **You only have {total_available} boost(s) left (daily {daily_rem}, extra {extra_rem}).**", color=discord.Color.red())
            await send_then_delete(ctx, embed)
            return

        if daily_rem >= votes:
            success, daily_used, extra_used = await use_vote(ctx.author, ctx.guild.id, votes)
            if not success:
                embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed to use votes.**", color=discord.Color.red())
                await send_then_delete(ctx, embed)
                return
            await add_vote_to_role(role.id, ctx.guild.id, ctx.author.id, votes)
            await create_boost_notification(user_id, ctx.guild.id, role.id, ctx.author.id, votes)
            new_daily = daily_rem - daily_used
            new_extra = extra_rem - extra_used
            embed = discord.Embed(description=f"{EMOJI_BOOSTED} **You boosted {role.mention} (owned by {member.mention}) with {votes} vote(s)!**\nRemaining daily: **{new_daily}**, extra: **{new_extra}**", color=discord.Color.green())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            await send_then_delete(ctx, embed)
        elif extra_rem >= votes:
            view = BoostConfirmView(ctx.author, role, votes, daily_rem, extra_rem, ctx)
            embed = discord.Embed(description=f"{EMOJI_WARNING} **Your daily boosts are over.**\nYou have **{extra_rem}** extra boost(s) left.\nDo you want to use {votes} extra boost(s) to boost {role.mention}?", color=discord.Color.orange())
            await ctx.send(embed=embed, view=view)
        else:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have enough boosts.** You need {votes} but have {daily_rem} daily + {extra_rem} extra.", color=discord.Color.red())
            await send_then_delete(ctx, embed)

# ---------- Unboost Command ----------
@bot.command(name="-boost")
async def unboost_command(ctx: commands.Context, target: str = None, amount: str = None):
    if target is None or amount is None:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Usage:** `!-boost <@user> <quantity/all>`\nExample: `!-boost @username 1` or `!-boost @username all`",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return

    user_id = None
    cleaned = target.strip('<@!>')
    if cleaned.isdigit():
        user_id = int(cleaned)
    else:
        member = discord.utils.get(ctx.guild.members, name=target)
        if member:
            user_id = member.id
    if not user_id:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid user.** Please mention a user (e.g., `@username`) or use their ID.", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    member = ctx.guild.get_member(user_id)
    if not member:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **User not found in this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    owned = await get_owned_role(user_id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{member.display_name} does not own a custom role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found. It may have been deleted.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    # How many boosts does the caller have available to spend?
    daily_rem = await get_daily_votes_remaining(ctx.author.id, ctx.guild.id)
    if daily_rem == -1:
        total_daily = await get_user_total_votes(ctx.author, ctx.guild.id)
        await reset_daily_votes(ctx.author.id, ctx.guild.id, total_daily)
        daily_rem = total_daily
    extra_rem = await get_user_extra_votes(ctx.author.id, ctx.guild.id)
    total_available = daily_rem + extra_rem

    if total_available == 0:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **You have no boosts left to spend.** Daily: **0**, Extra: **0**.",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed)
        return

    # How many boosts does the target role currently have?
    role_total = await get_total_votes_on_role(role_id, ctx.guild.id)
    if role_total == 0:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **{role.mention} has no boosts to remove.**",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed)
        return

    if amount.lower() == "all":
        votes = total_available
    else:
        try:
            votes = int(amount)
            if votes <= 0:
                raise ValueError
        except ValueError:
            embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid amount.** Use a positive number or `all`.", color=discord.Color.red())
            await send_then_delete(ctx, embed)
            return

    if votes > total_available:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **You only have {total_available} boost(s) to spend (daily: {daily_rem}, extra: {extra_rem}).**",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed)
        return

    # Cap at how many boosts the role actually has
    votes = min(votes, role_total)

    # Spend from caller's daily pool first, then extra
    if daily_rem >= votes:
        success, daily_used, extra_used = await use_vote(ctx.author, ctx.guild.id, votes)
    elif extra_rem >= votes:
        view = UnboostConfirmView(ctx.author, role, member, votes, daily_rem, extra_rem, ctx)
        embed = discord.Embed(
            description=(
                f"{EMOJI_WARNING} **Your daily boosts are over.**\n"
                f"You have **{extra_rem}** extra boost(s) left.\n"
                f"Do you want to spend {votes} extra boost(s) to remove boosts from {role.mention}?"
            ),
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, view=view)
        return
    else:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **You don't have enough boosts.** You need {votes} but have {daily_rem} daily + {extra_rem} extra.",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed)
        return

    if not success:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed to spend boosts.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    removed = await remove_any_votes_from_role(role_id, ctx.guild.id, votes)
    new_daily = daily_rem - daily_used
    new_extra = extra_rem - extra_used
    new_role_total = role_total - removed

    embed = discord.Embed(
        description=(
            f"{EMOJI_DELETE} **Removed {removed} boost(s) from {role.mention} (owned by {member.mention}).**\n"
            f"Role total boosts: **{new_role_total}**\n"
            f"Your remaining — daily: **{new_daily}**, extra: **{new_extra}**"
        ),
        color=discord.Color.orange()
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed, delay=8)


# ---------- Boosts Status Command ----------
@bot.command(name="boosts")
async def boosts_command(ctx: commands.Context):
    member = ctx.author
    daily_rem = await get_daily_votes_remaining(member.id, ctx.guild.id)
    if daily_rem == -1:
        total_daily = await get_user_total_votes(member, ctx.guild.id)
        await reset_daily_votes(member.id, ctx.guild.id, total_daily)
        daily_rem = total_daily
    total_daily = await get_user_total_votes(member, ctx.guild.id)
    extra_rem = await get_user_extra_votes(member.id, ctx.guild.id)
    total_rem = daily_rem + extra_rem

    if total_rem == 0:
        bar = "░" * 10
    else:
        filled = round((daily_rem / total_daily) * 10) if total_daily > 0 else 0
        bar = "█" * filled + "░" * (10 - filled)

    embed = discord.Embed(
        title=f"{EMOJI_BOOSTED} Your Boost Balance",
        color=discord.Color.green() if total_rem > 0 else discord.Color.red()
    )
    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
    embed.add_field(name="Daily", value=f"**{daily_rem}** / {total_daily}\n`{bar}`", inline=True)
    embed.add_field(name="Extra", value=f"**{extra_rem}**", inline=True)
    embed.add_field(name="Total Available", value=f"**{total_rem}**", inline=True)
    if daily_rem == 0 and extra_rem > 0:
        embed.set_footer(text="Daily boosts used up — extra boosts require confirmation.")
    elif total_rem == 0:
        embed.set_footer(text="No boosts left. Daily boosts reset every 24 hours.")
    await ctx.send(embed=embed)

# ---------- SLASH COMMANDS ----------
@bot.tree.command(name="role-info", description="Show your custom role details")
async def slash_role_info(interaction: discord.Interaction):
    await role_info_logic(interaction, interaction.user, interaction.guild)

@bot.tree.command(name="role-give", description="Give your custom role to another user")
@app_commands.describe(user="User to receive the role")
async def slash_role_give(interaction: discord.Interaction, user: discord.User):
    await role_give_logic(interaction, user, interaction.guild, interaction.user)

@bot.tree.command(name="role-add", description="[Admin] Create or extend a custom role for a user")
@app_commands.describe(user="User to receive or extend the custom role")
async def slash_role_add(interaction: discord.Interaction, user: discord.User):
    if not await is_admin_or_whitelisted(interaction.user, "role_add", interaction.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    await role_add_logic(interaction, user, interaction.guild, interaction.user)

@bot.tree.command(name="role-remove", description="[Admin] Remove custom role from a user")
@app_commands.describe(user="User to remove the custom role from")
async def slash_role_remove(interaction: discord.Interaction, user: discord.User):
    if not await is_admin_or_whitelisted(interaction.user, "role_remove", interaction.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    await role_remove_logic(interaction, user, interaction.guild)

@bot.tree.command(name="role-date", description="Check role validity and stacked credits")
@app_commands.describe(user="User to check (default: yourself)")
async def slash_role_date(interaction: discord.Interaction, user: Optional[discord.User] = None):
    if user is None:
        user = interaction.user
    await role_date_logic(interaction, user, interaction.guild)

@bot.tree.command(name="sys-edit", description="[Admin] Edit the role owned by a user")
@app_commands.describe(user="Owner of the role to edit")
async def slash_sys_edit(interaction: discord.Interaction, user: discord.User):
    if not await is_admin_or_whitelisted(interaction.user, "setup", interaction.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission to use this command.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    owned = await get_owned_role(user.id, interaction.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{user.mention} does not own any role.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    role_id, _, _ = owned
    role = interaction.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    with get_db() as conn:
        cur = conn.execute("SELECT name, icon_url FROM custom_roles WHERE role_id = ?", (role_id,))
        name, icon_url = cur.fetchone()
    embed = discord.Embed(title=f"{EMOJI_HAMMER} **Admin Role Manager**", description=f"{EMOJI_MEMO} **Name:** `{name}`\n{EMOJI_COLOR} **Color:** `{int_to_hex(role.color.value)}`\n{EMOJI_USER} **Owner:** {user.mention}", color=role.color)
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    view = RoleInfoView(role, role_id, interaction.user.id, interaction.guild, None)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    view.original_message = msg

@bot.tree.command(name="sys-value", description="[Admin] Add or remove days from a user's role")
@app_commands.describe(user="User whose role to modify", operation="add or rm", days="Number of days")
async def slash_sys_value(interaction: discord.Interaction, user: discord.User, operation: str, days: int):
    if not await is_admin_or_whitelisted(interaction.user, "setup", interaction.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission to use this command.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    membership = await get_user_role_membership(user.id, interaction.guild.id)
    if not membership:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{user.mention} does not have a custom role membership.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    role_id, stack_count, current_expiry, _ = membership
    if operation.lower() == "add":
        new_expiry = current_expiry + timedelta(days=days)
        action = "added"
    elif operation.lower() == "rm":
        new_expiry = current_expiry - timedelta(days=days)
        action = "removed"
    else:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid operation. Use `add` or `rm`.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    with get_db() as conn:
        conn.execute("UPDATE role_memberships SET expires_at = ? WHERE role_id = ? AND user_id = ?",
                     (new_expiry, role_id, user.id))
        conn.commit()
    remaining = new_expiry - datetime.now(timezone.utc)
    if remaining.total_seconds() <= 0:
        remaining_text = "Expired"
    else:
        d = remaining.days
        h = remaining.seconds // 3600
        m = (remaining.seconds % 3600) // 60
        remaining_text = f"{d} days, {h} hours, {m} minutes"
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{action} {days} days to {user.display_name}'s role.**\n{EMOJI_INFO} Time remaining: **{remaining_text}**", color=discord.Color.green())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    await send_then_delete(interaction, embed)

@bot.tree.command(name="role-overview", description="Show ranking, creators, and most users")
async def slash_role_overview(interaction: discord.Interaction):
    view = OverviewView(interaction.guild, interaction.user, 0, "rankings")
    await view.initialize()
    await interaction.response.send_message(embed=view.embed, view=view)

@bot.tree.command(name="role-list", description="Show list of all custom roles (creators)")
async def slash_role_list(interaction: discord.Interaction):
    view = OverviewView(interaction.guild, interaction.user, 0, "creators")
    await view.initialize()
    await interaction.response.send_message(embed=view.embed, view=view)

@bot.tree.command(name="sys-boost", description="[Admin] Configure booster roles and daily limit")
async def slash_sys_boost(interaction: discord.Interaction):
    if not await is_admin_or_whitelisted(interaction.user, "setup", interaction.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission to use this command.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await send_then_delete(interaction, embed)
        return
    view = BoostAdminView(interaction.guild)
    embed = discord.Embed(title=f"{EMOJI_GEAR} **Boost System Admin**", description="Manage booster roles, user extras, and daily limit.", color=discord.Color.blue())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="setup", description="[Admin] Configure the bot for this server")
async def slash_setup(interaction: discord.Interaction):
    if not await is_admin_or_whitelisted(interaction.user, "setup", interaction.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission to use setup.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    await _show_setup_embed(interaction, edit=False)

@bot.tree.command(name="server-stats", description="[Admin] Show a summary of all bot data stored for this server")
async def slash_server_stats(interaction: discord.Interaction):
    if not await is_admin_or_whitelisted(interaction.user, "setup", interaction.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission to use this command.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id

    with get_db() as conn:
        # Guild config
        cur = conn.execute("SELECT prefix, role_add_whitelist, role_remove_whitelist, trigger_role_id, daily_vote_limit FROM guild_config WHERE guild_id = ?", (guild_id,))
        config_row = cur.fetchone()

        # Custom roles count
        cur = conn.execute("SELECT COUNT(*) FROM custom_roles WHERE guild_id = ?", (guild_id,))
        role_count = cur.fetchone()[0]

        # Role memberships count (across all roles in this guild)
        cur = conn.execute("""
            SELECT COUNT(*) FROM role_memberships rm
            JOIN custom_roles cr ON rm.role_id = cr.role_id
            WHERE cr.guild_id = ?
        """, (guild_id,))
        membership_count = cur.fetchone()[0]

        # Total votes cast this week
        now = datetime.now(timezone.utc)
        start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        cur = conn.execute("SELECT COUNT(*) FROM vote_log WHERE guild_id = ? AND voted_at >= ?", (guild_id, start_of_week))
        weekly_votes = cur.fetchone()[0]

        # Total all-time votes
        cur = conn.execute("SELECT COUNT(*) FROM vote_log WHERE guild_id = ?", (guild_id,))
        total_votes = cur.fetchone()[0]

        # Users with extra boosts
        cur = conn.execute("SELECT COUNT(*), COALESCE(SUM(extra_votes), 0) FROM user_extra_votes WHERE guild_id = ?", (guild_id,))
        extra_row = cur.fetchone()
        users_with_extra = extra_row[0]
        total_extra_votes = extra_row[1]

        # Booster roles
        cur = conn.execute("SELECT COUNT(*) FROM booster_roles WHERE guild_id = ?", (guild_id,))
        booster_role_count = cur.fetchone()[0]

        # Users with gradient permission
        cur = conn.execute("SELECT COUNT(*) FROM gradient_permissions WHERE guild_id = ?", (guild_id,))
        gradient_granted = cur.fetchone()[0]

        # User settings (highlighted roles)
        cur = conn.execute("SELECT COUNT(*) FROM user_settings WHERE guild_id = ? AND highlighted_role_id IS NOT NULL", (guild_id,))
        highlighted_count = cur.fetchone()[0]

        # Expired memberships still in DB (already past expiry)
        cur = conn.execute("""
            SELECT COUNT(*) FROM role_memberships rm
            JOIN custom_roles cr ON rm.role_id = cr.role_id
            WHERE cr.guild_id = ? AND rm.expires_at <= ?
        """, (guild_id, now))
        expired_count = cur.fetchone()[0]

    # Build embed
    gradient_available = can_use_gradient(interaction.guild)
    boost_status = f"Level {interaction.guild.premium_tier} {'✅ Unlocked' if gradient_available else '🔒 Locked (needs Level 3)'}"

    if config_row:
        prefix, add_wl, remove_wl, trigger_id, daily_limit = config_row
        trigger_mention = interaction.guild.get_role(trigger_id).mention if trigger_id and interaction.guild.get_role(trigger_id) else "None"
        add_wl_count = len([x for x in (add_wl or "").split(",") if x.strip()])
        remove_wl_count = len([x for x in (remove_wl or "").split(",") if x.strip()])
    else:
        prefix, daily_limit, trigger_mention = "!", 1, "None"
        add_wl_count = remove_wl_count = 0

    embed = discord.Embed(
        title=f"{EMOJI_GEAR} **Server Data Summary**",
        description=f"All bot data currently stored for **{interaction.guild.name}**.",
        color=discord.Color.blue()
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

    embed.add_field(name=f"{EMOJI_GEAR} Config", value=(
        f"Prefix: `{prefix}`\n"
        f"Trigger Role: {trigger_mention}\n"
        f"Daily Vote Limit: `{daily_limit}`\n"
        f"Add Whitelist Entries: `{add_wl_count}`\n"
        f"Remove Whitelist Entries: `{remove_wl_count}`"
    ), inline=False)

    embed.add_field(name=f"{EMOJI_PERFORMINGARTS} Roles", value=(
        f"Custom Roles: `{role_count}`\n"
        f"Total Memberships: `{membership_count}`\n"
        f"Expired (pending cleanup): `{expired_count}`\n"
        f"Display Role Settings: `{highlighted_count}`"
    ), inline=False)

    embed.add_field(name=f"{EMOJI_BOOSTED_COUNT} Votes & Boosts", value=(
        f"Votes This Week: `{weekly_votes}`\n"
        f"All-Time Votes: `{total_votes}`\n"
        f"Booster Roles Configured: `{booster_role_count}`\n"
        f"Users With Extra Boosts: `{users_with_extra}` (`{total_extra_votes}` total extra)"
    ), inline=False)

    embed.add_field(name=f"{BTN_GRADIENT} Enhance Color", value=(
        f"Server Boost: {boost_status}\n"
        f"Users Granted Access: `{gradient_granted}`"
    ), inline=False)

    embed.set_footer(text="Use /setup → Clear Cache to wipe all of this data.")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="grant-style", description="[Admin] Grant or revoke Enhance Color access for any user")
@app_commands.describe(user="The user to grant or revoke access for")
async def slash_grant_style(interaction: discord.Interaction, user: discord.User):
    if not interaction.user.guild_permissions.administrator:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Admin only.**", color=discord.Color.red())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    has = await has_gradient_permission(user.id, interaction.guild.id)
    gradient_available = can_use_gradient(interaction.guild)
    boost_note = ""
    if not gradient_available:
        boost_note = (
            f"\n\n{EMOJI_WARNING} *This server is at Boost Level **{interaction.guild.premium_tier}**. "
            f"Enhance Color requires **Level 3** — access is saved and will activate once the server is boosted.*"
        )

    if has:
        await revoke_gradient_permission(user.id, interaction.guild.id)
        embed = discord.Embed(
            description=f"{EMOJI_SUCCESS} **Revoked Enhance Color access from {user.mention}.**{boost_note}",
            color=discord.Color.orange()
        )
    else:
        await grant_gradient_permission(user.id, interaction.guild.id)
        embed = discord.Embed(
            description=f"{EMOJI_SUCCESS} **Granted Enhance Color access to {user.mention}.**{boost_note}",
            color=discord.Color.green()
        )

    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="help", description="Show help")
async def slash_help(interaction: discord.Interaction):
    await send_help_embed(interaction, interaction.user, interaction.guild)

# ---------- PREFIX COMMANDS ----------
@bot.group(name="role", invoke_without_command=True)
async def prefix_role_group(ctx: commands.Context):
    await role_info_logic(ctx, ctx.author, ctx.guild)

@prefix_role_group.command(name="info")
async def prefix_role_info(ctx: commands.Context):
    await role_info_logic(ctx, ctx.author, ctx.guild)

@prefix_role_group.command(name="give")
async def prefix_role_give(ctx: commands.Context, user: discord.User = None):
    if user is None:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!role give <@user>`", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    await role_give_logic(ctx, user, ctx.guild, ctx.author)

@prefix_role_group.command(name="add")
async def prefix_role_add(ctx: commands.Context, user: discord.User):
    if not await is_admin_or_whitelisted(ctx.author, "role_add", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    await role_add_logic(ctx, user, ctx.guild, ctx.author)

@prefix_role_group.command(name="remove")
async def prefix_role_remove(ctx: commands.Context, user: discord.User):
    if not await is_admin_or_whitelisted(ctx.author, "role_remove", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    await role_remove_logic(ctx, user, ctx.guild)

@prefix_role_group.command(name="date")
async def prefix_role_date(ctx: commands.Context, user: discord.User = None):
    if user is None:
        user = ctx.author
    await role_date_logic(ctx, user, ctx.guild)

@prefix_role_group.command(name="overview")
async def prefix_role_overview(ctx: commands.Context):
    view = OverviewView(ctx.guild, ctx.author, 0, "rankings")
    await view.initialize()
    await ctx.send(embed=view.embed, view=view)

@prefix_role_group.command(name="list")
async def prefix_role_list(ctx: commands.Context):
    view = OverviewView(ctx.guild, ctx.author, 0, "creators")
    await view.initialize()
    await ctx.send(embed=view.embed, view=view)

# ---------- Set Group (prefix) ----------
@bot.group(name="set", invoke_without_command=True)
async def prefix_set_group(ctx: commands.Context):
    embed = discord.Embed(
        description=(
            f"{EMOJI_INFO} **Usage:**\n"
            f"`!set name <new name>` — change your role name\n"
            f"`!set color <hex>` — change your role color (e.g. `#ff0000`)\n"
            f"`!set emoji <emoji or id>` — set your role icon from an emoji\n"
            f"`!set icon` — attach an image to set as role icon\n"
            f"`!set gradient <color1> <color2>` — set gradient colors (e.g. `!set gradient #ff0000 #0000ff`)"
        ),
        color=discord.Color.blue()
    )
    await send_then_delete(ctx, embed)

@prefix_set_group.command(name="name")
async def set_name(ctx: commands.Context, *, new_name: str = None):
    if not new_name:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!set name <new name>`", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    owned = await get_owned_role(ctx.author.id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't own a custom role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    await role.edit(name=new_name)
    with get_db() as conn:
        conn.execute("UPDATE custom_roles SET name = ? WHERE role_id = ?", (new_name, role_id))
        conn.commit()
    await ensure_role_highlighted(role, ctx.guild)
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Role name set to `{new_name}`**", color=discord.Color.green())
    await send_then_delete(ctx, embed)

@prefix_set_group.command(name="color")
async def set_color(ctx: commands.Context, hex_code: str = None):
    if not hex_code:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!set color <hex>` e.g. `!set color #ff0000`", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    try:
        color_int = hex_to_int(hex_code)
    except ValueError:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Invalid hex color.** Use format like `#ff0000` or `ff0000`.", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    owned = await get_owned_role(ctx.author.id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't own a custom role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    await role.edit(color=discord.Color(color_int))
    with get_db() as conn:
        conn.execute("UPDATE custom_roles SET color = ? WHERE role_id = ?", (color_int, role_id))
        conn.commit()
    await ensure_role_highlighted(role, ctx.guild)
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Role color set to `{int_to_hex(color_int)}`**", color=discord.Color(color_int))
    await send_then_delete(ctx, embed)

@prefix_set_group.command(name="emoji")
async def set_emoji(ctx: commands.Context, emoji_input: str = None):
    if not emoji_input:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!set emoji <emoji or emoji id>`", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    url = emoji_to_url(emoji_input)
    if not url:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Could not recognise the emoji.**\nOnly **custom emojis** (with an ID) can be used as role icons.", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    owned = await get_owned_role(ctx.author.id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't own a custom role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    with get_db() as conn:
        conn.execute("UPDATE custom_roles SET icon_url = ? WHERE role_id = ?", (url, role_id))
        conn.commit()
    icon_error = ""
    if ctx.guild.premium_tier < 2:
        icon_error = f"\n{EMOJI_WARNING} *Role icon display requires **Boost Level 2**. Icon saved but not yet applied to the role.*"
    else:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200 and resp.content_type.startswith('image/'):
                        img_data = _process_icon_bytes(await resp.read())
                        await role.edit(icon=img_data)
                    else:
                        icon_error = f"\n{EMOJI_WARNING} *Could not download image from that URL (HTTP {resp.status}). Make sure the link points directly to an image file.*"
        except Exception as e:
            icon_error = f"\n{_icon_error_msg(e)}"
    await ensure_role_highlighted(role, ctx.guild)
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Role icon updated!**{icon_error}", color=discord.Color.green())
    embed.set_thumbnail(url=url)
    await send_then_delete(ctx, embed, delay=4)

@prefix_set_group.command(name="icon")
async def set_icon(ctx: commands.Context):
    # Resolve the attachment: from the command message itself OR a replied-to message
    attachment = None
    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
    elif ctx.message.reference:
        try:
            ref_msg = ctx.message.reference.resolved
            if ref_msg is None:
                ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if ref_msg and ref_msg.attachments:
                attachment = ref_msg.attachments[0]
        except (discord.NotFound, discord.HTTPException):
            pass

    if not attachment:
        embed = discord.Embed(
            description=(
                f"{EMOJI_ERROR} **No image found.**\n\n"
                f"Either attach an image directly to your `!set icon` message, "
                f"or **reply** to a message that contains an image."
            ),
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return

    if not attachment.content_type or not attachment.content_type.startswith('image/'):
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **That attachment isn't an image.** Please use PNG, JPG, GIF, or WEBP.",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return

    owned = await get_owned_role(ctx.author.id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't own a custom role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return

    raw_data = await attachment.read()
    img_data = _process_icon_bytes(raw_data)

    with get_db() as conn:
        conn.execute("UPDATE custom_roles SET icon_url = ? WHERE role_id = ?", (attachment.url, role_id))
        conn.commit()

    icon_error = ""
    if ctx.guild.premium_tier < 2:
        icon_error = f"\n{EMOJI_WARNING} *Role icon display requires **Boost Level 2**. Icon saved but not yet applied to the role.*"
    else:
        try:
            await role.edit(icon=img_data)
        except Exception as e:
            icon_error = f"\n{_icon_error_msg(e)}"

    await ensure_role_highlighted(role, ctx.guild)
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Role icon updated!**{icon_error}", color=discord.Color.green())
    embed.set_thumbnail(url=attachment.url)
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed, delay=4)

@prefix_set_group.command(name="gradient")
async def set_gradient(ctx: commands.Context, color1: str = None, color2: str = None):
    if not color1 or not color2:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Usage:** `!set gradient <color1> <color2>` e.g. `!set gradient #ff0000 #0000ff`",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return
    try:
        color1_int = hex_to_int(color1)
        color2_int = hex_to_int(color2)
    except ValueError:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Invalid hex color.** Use format like `#ff0000` or `ff0000`.",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed)
        return
    if not await can_user_use_gradient(ctx.author, ctx.guild):
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **You don't have Enhance Color (gradient) access.**\nWin the weekly boost ranking or ask an admin to grant you access via `/grant-style`.",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed)
        return
    owned = await get_owned_role(ctx.author.id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't own a custom role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    with get_db() as conn:
        conn.execute(
            "UPDATE custom_roles SET gradient_colors = ? WHERE role_id = ?",
            (f"{color1_int},{color2_int}", role_id)
        )
        conn.commit()
    color_note = ""
    try:
        await _apply_gradient_to_role(role, color1_int, color2_int)
    except Exception as ce:
        color_note = f"\n{EMOJI_WARNING} *Could not apply gradient — check bot permissions and role hierarchy: {ce}*"
    embed = discord.Embed(
        description=(
            f"{EMOJI_SUCCESS} **Gradient colors applied!**\n"
            f"Color 1: `{int_to_hex(color1_int)}` · Color 2: `{int_to_hex(color2_int)}`{color_note}"
        ),
        color=discord.Color(color1_int)
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed, delay=5)

# ---------- Sys Group (prefix) ----------
@bot.group(name="sys", invoke_without_command=True)
async def prefix_sys_group(ctx: commands.Context):
    embed = discord.Embed(description=f"{EMOJI_INFO} **Usage: `!sys role edit @user` or `!sys role value @user add/rm <days>`**\n`!sys add boost @role <number>` or `!sys add vote @user <number>`\n`!sys add extra @user <number>`", color=discord.Color.blue())
    await send_then_delete(ctx, embed)

@prefix_sys_group.group(name="add", invoke_without_command=True)
async def sys_add_group(ctx: commands.Context):
    embed = discord.Embed(description=f"{EMOJI_INFO} **Usage:** `!sys add boost @role <number>` or `!sys add vote @user <number>` or `!sys add extra @user <number>`", color=discord.Color.blue())
    await send_then_delete(ctx, embed)

@sys_add_group.command(name="boost")
@commands.has_permissions(administrator=True)
async def sys_add_boost(ctx: commands.Context, role: discord.Role, amount: int):
    if amount <= 0:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Amount must be positive.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    await add_booster_role(ctx.guild.id, role.id, amount)
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{role.mention}** now grants **{amount}** extra votes per day.", color=discord.Color.green())
    await send_then_delete(ctx, embed)

@sys_add_group.command(name="vote")
@commands.has_permissions(administrator=True)
async def sys_add_vote(ctx: commands.Context, user: discord.User, amount: int):
    if amount <= 0:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Amount must be positive.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    await set_user_extra_votes(user.id, ctx.guild.id, amount)
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{user.mention}** now gets **{amount}** extra votes per day (extra boosts).", color=discord.Color.green())
    await send_then_delete(ctx, embed)

@sys_add_group.command(name="extra")
@commands.has_permissions(administrator=True)
async def sys_add_extra(ctx: commands.Context, user: discord.User, amount: int):
    if amount <= 0:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Amount must be positive.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    await add_user_extra_votes(user.id, ctx.guild.id, amount)
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Added {amount} extra boost(s) to {user.mention}.**", color=discord.Color.green())
    await send_then_delete(ctx, embed)

@sys_add_group.command(name="boostadd")
@commands.has_permissions(administrator=True)
async def sys_add_boostadd(ctx: commands.Context, user: discord.User, amount: int):
    await sys_add_extra(ctx, user, amount)

@prefix_sys_group.group(name="role", invoke_without_command=True)
async def prefix_sys_role_group(ctx: commands.Context):
    await role_info_logic(ctx, ctx.author, ctx.guild)

@prefix_sys_role_group.command(name="edit")
@commands.has_permissions(administrator=True)
async def prefix_sys_role_edit(ctx: commands.Context, user: discord.User):
    owned = await get_owned_role(user.id, ctx.guild.id)
    if not owned:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{user.mention} does not own any role.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    role_id, _, _ = owned
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Role not found.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    with get_db() as conn:
        cur = conn.execute("SELECT name, icon_url FROM custom_roles WHERE role_id = ?", (role_id,))
        name, icon_url = cur.fetchone()
    embed = discord.Embed(title=f"{EMOJI_HAMMER} **Admin Role Manager**", description=f"{EMOJI_MEMO} **Name:** `{name}`\n{EMOJI_COLOR} **Color:** `{int_to_hex(role.color.value)}`\n{EMOJI_USER} **Owner:** {user.mention}", color=role.color)
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    view = RoleInfoView(role, role_id, ctx.author.id, ctx.guild, None)
    sent_msg = await ctx.send(embed=embed, view=view)
    view.original_message = sent_msg

@prefix_sys_role_group.command(name="value")
@commands.has_permissions(administrator=True)
async def prefix_sys_role_value(ctx: commands.Context, user: discord.User, operation: str = None, days: int = 0):
    if operation not in ["add", "rm"] or days == 0:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!sys role value <@user> <add/rm> <days>`\nExample: `!sys role value @user add 7` or `!sys role value @user rm 3`", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    membership = await get_user_role_membership(user.id, ctx.guild.id)
    if not membership:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{user.mention} does not have a custom role membership.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    role_id, stack_count, current_expiry, _ = membership
    if operation.lower() == "add":
        new_expiry = current_expiry + timedelta(days=days)
        action = "added"
    else:
        new_expiry = current_expiry - timedelta(days=days)
        action = "removed"
    with get_db() as conn:
        conn.execute("UPDATE role_memberships SET expires_at = ? WHERE role_id = ? AND user_id = ?",
                     (new_expiry, role_id, user.id))
        conn.commit()
    remaining = new_expiry - datetime.now(timezone.utc)
    if remaining.total_seconds() <= 0:
        remaining_text = "Expired"
    else:
        d = remaining.days
        h = remaining.seconds // 3600
        m = (remaining.seconds % 3600) // 60
        remaining_text = f"{d} days, {h} hours, {m} minutes"
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **{action} {days} days to {user.display_name}'s role.**\n{EMOJI_INFO} Time remaining: **{remaining_text}**", color=discord.Color.green())
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed)

# ---------- Prefix Help ----------

# ---------- Help Embed Helper ----------
async def send_help_embed(ctx_or_inter, user: discord.Member, guild: discord.Guild):
    is_admin = await is_admin_or_whitelisted(user, "setup", guild)
    lvl_cfg = get_lvl_config(guild.id)
    lvl_enabled = bool(lvl_cfg.get("enabled"))

    embed = discord.Embed(
        title=f"{EMOJI_PERFORMINGARTS} **Welcome to Custom Roles!**",
        description=(
            f"This bot lets server members own and customise their own Discord role — "
            f"change its name, color, icon, and give it to others.\n\n"
            f"{EMOJI_STAR} **What you can do:**\n"
            f"• Own a personal role with a custom name, color & icon\n"
            f"• Give your role to other members\n"
            f"• Boost other members' roles to support them\n"
            f"• Display a role at the top of your profile\n"
            f"• Track your role's validity and stacked credits\n\n"
            f"{EMOJI_GEAR} **Admins can:**\n"
            f"• Create and manage roles for users\n"
            f"• Configure booster roles and vote limits\n"
            f"• Set a trigger role that auto-creates roles\n"
            f"• Adjust whitelist and server settings\n\n"
            f"*Thank you for using Custom Roles — enjoy your role!* {EMOJI_SUCCESS}"
        ),
        color=discord.Color.blurple()
    )
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
    embed.set_footer(text="Use the buttons below to explore commands.")

    view = HelpView(is_admin, lvl_enabled)

    if isinstance(ctx_or_inter, discord.Interaction):
        await ctx_or_inter.response.send_message(embed=embed, view=view, ephemeral=True)
    else:
        await ctx_or_inter.send(embed=embed, view=view)


class HelpView(DisableOnTimeoutView):
    def __init__(self, is_admin: bool, lvl_enabled: bool = False):
        super().__init__(timeout=120)
        self._is_admin = is_admin
        self._lvl_enabled = lvl_enabled
        # Back button is hidden on the main welcome page; shown only after navigating in
        self._set_back(False)

    def _set_back(self, enabled: bool):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Back":
                child.disabled = not enabled
                break

    def _user_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"{EMOJI_USER} **User Commands**",
            color=discord.Color.blurple()
        )
        embed.add_field(name=f"`!role` / `!role info`", value="View your custom role details & edit menu", inline=False)
        embed.add_field(name=f"`!role give @user`", value="Give your custom role to another member", inline=False)
        embed.add_field(name=f"`!role date [@user]`", value="Check role validity & stacked credits", inline=False)
        embed.add_field(name=f"`!role overview`", value="Server-wide role rankings & stats", inline=False)
        embed.add_field(name=f"`!role list`", value="List all custom roles in this server", inline=False)
        embed.add_field(name=f"`!boost @user <amount/all>`", value="Boost a member's role with your daily votes", inline=False)
        embed.add_field(name=f"`!boosts`", value="Check your remaining daily & extra boosts", inline=False)
        embed.add_field(name=f"`!set name <name>`", value="Change your role's display name", inline=False)
        embed.add_field(name=f"`!set color <#hex>`", value="Change your role's color", inline=False)
        embed.add_field(name=f"`!set emoji <emoji>`", value="Set your role icon from a custom emoji", inline=False)
        embed.add_field(name=f"`!set icon` + attach/reply", value="Set your role icon from an uploaded image", inline=False)
        embed.set_footer(text="Prefix commands shown. Slash equivalents also available.")
        return embed

    def _admin_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"{EMOJI_HAMMER} **Server Settings & Admin Commands**",
            color=discord.Color.red()
        )
        embed.add_field(name=f"`!role add @user`", value="Create a custom role for a user (30-day validity)", inline=False)
        embed.add_field(name=f"`!role remove @user`", value="Remove a user's custom role entirely", inline=False)
        embed.add_field(name=f"`!sys role edit @user`", value="Open the role editor for any user's role", inline=False)
        embed.add_field(name=f"`!sys role value @user add/rm <days>`", value="Add or subtract days from a role's validity", inline=False)
        embed.add_field(name=f"`!sys add boost @role <votes>`", value="Give a role extra daily boost votes", inline=False)
        embed.add_field(name=f"`!sys add extra @user <amount>`", value="Grant extra boosts to a specific user", inline=False)
        embed.add_field(name=f"`!setup`", value="Configure prefix, whitelist, trigger role & gradient access", inline=False)
        embed.add_field(name=f"`/grant-style @user`", value="Grant or revoke Enhance Color access", inline=False)
        embed.add_field(name=f"`/server-stats`", value="View a full summary of all bot data for this server", inline=False)
        embed.add_field(name=f"`/sys-boost`", value="Configure booster roles and daily vote limits", inline=False)
        embed.set_footer(text="Admin-only commands. Whitelisted users can also run role-add/remove.")
        return embed

    @discord.ui.button(emoji=EMOJI_USER, label="User", style=discord.ButtonStyle.primary, row=0)
    async def user_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_back(True)
        await interaction.response.edit_message(embed=self._user_embed(), view=self)

    @discord.ui.button(emoji=EMOJI_HAMMER, label="Server Settings", style=discord.ButtonStyle.danger, row=0)
    async def admin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{EMOJI_ERROR} **This section is for admins and whitelisted users only.**",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
        self._set_back(True)
        await interaction.response.edit_message(embed=self._admin_embed(), view=self)

    @discord.ui.button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_back(False)
        embed = discord.Embed(
            title=f"{EMOJI_PERFORMINGARTS} **Welcome to Custom Roles!**",
            description=(
                f"This bot lets server members own and customise their own Discord role — "
                f"change its name, color, icon, and give it to others.\n\n"
                f"{EMOJI_STAR} **What you can do:**\n"
                f"• Own a personal role with a custom name, color & icon\n"
                f"• Give your role to other members\n"
                f"• Boost other members' roles to support them\n"
                f"• Display a role at the top of your profile\n"
                f"• Track your role's validity and stacked credits\n\n"
                f"{EMOJI_GEAR} **Admins can:**\n"
                f"• Create and manage roles for users\n"
                f"• Configure booster roles and vote limits\n"
                f"• Set a trigger role that auto-creates roles\n"
                f"• Adjust whitelist and server settings\n\n"
                f"*Thank you for using Custom Roles — enjoy your role!* {EMOJI_SUCCESS}"
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="<:Level:1510458145846198562>", label="Level", style=discord.ButtonStyle.success, row=1)
    async def level_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._lvl_enabled:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{EMOJI_LVL_LOCKED} **Leveling is not enabled on this server.**",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
        self._set_back(True)
        embed = discord.Embed(
            title=f"{EMOJI_LVL_LEVEL} **Level & Perks**",
            color=discord.Color.blurple()
        )
        embed.add_field(name=f"`!lvl [@user]`", value="View your level progress card (or another member's)", inline=False)
        embed.add_field(name=f"`!xp [@user]`", value="Check total XP earned", inline=False)
        embed.add_field(name=f"`!prestige`", value="Unlock the next prestige tier (requires Level 100)", inline=False)
        embed.add_field(name=f"`.bless [small/medium/large] @user`", value="Bless a member with an XP multiplier boost (VIP/Elite/Supreme only)", inline=False)
        embed.add_field(name=f"`.bless status`", value="Check your own active blessing", inline=False)
        embed.add_field(name=f"`!reaction set [emoji1] ...`", value="Set up to 5 mention reactions — triggers anywhere you're mentioned (Elite/Supreme only)", inline=False)
        embed.add_field(name=f"`!vote`", value="View the server vote link and earn credits", inline=False)
        embed.add_field(name=f"`!donor`", value="Browse VIP / Elite / Supreme perks and credit costs", inline=False)
        embed.add_field(name=f"`!vc invite @user`", value="Invite a member into your personal voice channel", inline=False)
        embed.set_footer(text="Only available when leveling is enabled on this server.")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji=EMOJI_HAMMER, label="Level management", style=discord.ButtonStyle.danger, row=1)
    async def level_mgmt_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{EMOJI_ERROR} **This section is for admins and whitelisted users only.**",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
        if not self._lvl_enabled:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{EMOJI_LVL_LOCKED} **Leveling is not enabled on this server.**",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
        self._set_back(True)
        embed = discord.Embed(
            title=f"{EMOJI_HAMMER} **Level Management**",
            color=discord.Color.red()
        )
        embed.add_field(name=f"`!e addrole <1-3> @user <n> <m/y>`", value="Grant VIP/Elite/Supreme for a set time\n**1** VIP · **2** Elite · **3** Supreme · `m`=months · `y`=years", inline=False)
        embed.add_field(name=f"`!e removerole @user`", value="Revoke a tier role — if user has multiple, shows a picker", inline=False)
        embed.add_field(name=f"`!e addbooster <1-8> @user [qty]`", value="Give a user an XP booster\n**1** 1hr 2x · **2** 12hr 2x · **3** 24hr 2x · **4** 1hr 3x · **5** 12hr 3x · **6** 24hr 3x · **7** 24hr 5x · **8** 3d 5x", inline=False)
        embed.add_field(name=f"`!e removebooster <1-8> @user [qty]`", value="Remove inventory boosters from a user", inline=False)
        embed.add_field(name=f"`!e extend @user <pct%>`", value="Give a user a temporary XP % boost for 1 hour", inline=False)
        embed.add_field(name=f"`!e addcredits @user <amount>`", value="Add or subtract credits from a user (use negative to subtract)", inline=False)
        embed.add_field(name=f"`!e vc setup`", value="Set up the Donor-Join voice channel hub (shows a category picker)", inline=False)
        embed.add_field(name=f"`!e vc perm @user <t/p>`", value="Grant VC access: **t** = temporary · **p** = permanent", inline=False)
        embed.set_footer(text="Admin and whitelisted users only.")
        await interaction.response.edit_message(embed=embed, view=self)

@bot.command(name="help")
async def prefix_help(ctx: commands.Context):
    await send_help_embed(ctx, ctx.author, ctx.guild)

# ---------- Setup command (prefix) ----------
@bot.command(name="setup")
async def prefix_setup(ctx: commands.Context):
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have permission to use setup.**", color=discord.Color.red())
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        await send_then_delete(ctx, embed)
        return
    with get_db() as conn:
        cur = conn.execute("SELECT prefix FROM guild_config WHERE guild_id = ?", (ctx.guild.id,))
        row = cur.fetchone()
        prefix = row[0] if row else "!"
    with get_db() as conn:
        cur = conn.execute("SELECT role_add_whitelist, role_remove_whitelist, trigger_role_id FROM guild_config WHERE guild_id = ?", (ctx.guild.id,))
        row2 = cur.fetchone()
    add_whitelist, remove_whitelist, trigger_role_id = row2 if row2 else ("", "", None)

    def resolve_mentions(ids_str):
        if not ids_str:
            return "None (only admins)"
        ids = [x.strip() for x in ids_str.split(',') if x.strip().isdigit()]
        if not ids:
            return "None (only admins)"
        parts = []
        for id_str in ids:
            id_ = int(id_str)
            role = ctx.guild.get_role(id_)
            if role:
                parts.append(role.mention)
            else:
                member = ctx.guild.get_member(id_)
                parts.append(member.mention if member else f"`{id_str}`")
        return ', '.join(parts) if parts else "None (only admins)"

    trigger_role_mention = "None"
    if trigger_role_id:
        tr = ctx.guild.get_role(trigger_role_id)
        if tr:
            trigger_role_mention = tr.mention

    embed = discord.Embed(title=f"{EMOJI_GEAR} **Bot Configuration**", color=discord.Color.blue())
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.add_field(name=f"{EMOJI_PIN} **Current Prefix**", value=f"`{prefix}`", inline=False)
    embed.add_field(name=f"{EMOJI_ADD} **Role Add Whitelist**", value=resolve_mentions(add_whitelist), inline=False)
    embed.add_field(name=f"{BTN_TRIGGER} **Trigger Role**", value=trigger_role_mention, inline=False)
    view = _make_setup_view(ctx.guild.id, prefix)
    await ctx.send(embed=embed, view=view)


# ═══════════════════════════════════════════════════════════════════════════════
# LEVELING SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

import random
import math

# ---------- Leveling Emojis ----------
EMOJI_LVL_LEVEL    = "<:Level:1510458145846198562>"
EMOJI_LVL_INFO     = "<:Info:1510457474313097296>"
EMOJI_LVL_EXTEND   = "<:extend_end:1510130984794722426>"
EMOJI_LVL_XP       = "<:xp:1509784671473631272>"
EMOJI_LVL_ROCKET   = "🚀"
EMOJI_LVL_LOCKED   = "<:locked:1509746506759143524>"
EMOJI_LVL_UNLOCKED = "<:unlocked:1509746459065581639>"
EMOJI_LVL_NICK     = "<:lvl_nickname:1509746947085307965>"
EMOJI_LVL_EMOTES   = "<:lvl_emotes:1509746919352565871>"
EMOJI_LVL_STREAM   = "<:lvl_streaming:1509746889216491652>"
EMOJI_LVL_VOICE    = "<:lvl_voice_message:1509746855569788998>"
EMOJI_LVL_SOUND    = "<:lvl_soundboard:1509746822371999946>"
EMOJI_LVL_POLLS    = "<:lvl_polls:1509746781649506474>"
EMOJI_LVL_IMAGE    = "<:lvl_image:1509746744391635087>"
EMOJI_LVL_EXTSND   = "<:lvl_external_sounds:1509746708785926184>"
EMOJI_LVL_BOOST    = "<:lvl_boost:1509746660283252888>"
EMOJI_LVL_2XP      = "<:lvl_2x_xp:1509746627894579301>"
EMOJI_LVL_THREADS  = "<:lvl_threads:1509746584399773767>"
EMOJI_LVL_PRESTIGE = "<:lvl_prestige:1509746549650100385>"
EMOJI_LVL_SETTINGS = "<:Settings:1509760339770740897>"
EMOJI_LVL_REWARD   = "<:Reward:1509760253473067068>"
EMOJI_LVL_CHAT     = "<:chat:1509784595393150976>"
EMOJI_LVL_INCREASE = "<:increase:1509785679683522670>"
EMOJI_LVL_PROGRESS = "<:Progress:1510474789771284490>"
EMOJI_LVL_TIME     = "<:Time:1510474726508728540>"
EMOJI_LVL_ACTION   = "<:Action:1510474524636872784>"
EMOJI_LVL_BLESS    = "<:Bless:1510474884063690802>"
EMOJI_LVL_CAL      = "<:calender:1507252185761710091>"
EMOJI_LVL_USER_XP  = "<:user_xp:1509760615445561416>"
EMOJI_LVL_CREDITS  = "<:Credits:1509751161564041457>"
EMOJI_LVL_BOOSTERS = "<:Boosters:1509751861228474438>"
EMOJI_LVL_VIP      = "<:VIP:1510540563831853226>"
EMOJI_LVL_ELITE    = "<:Elite:1510540609616609331>"
EMOJI_LVL_SUPREME  = "<:Supreme:1510540642785427587>"
EMOJI_LVL_DOUBLE   = "<:Double:1510465345209766008>"
EMOJI_LVL_TRIPLE   = "<:Triple:1510465422976094348>"
EMOJI_LVL_5X       = "<:5x:1510465157896339496>"

EMOJI_BOOST_10  = "<:booster_10:1509785383817183483>"
EMOJI_BOOST_25  = "<:booster_25:1509785315680714864>"
EMOJI_BOOST_50  = "<:booster_50:1509785350636048524>"
EMOJI_BOOST_75  = "<:booster_75:1509785449542193345>"
EMOJI_BOOST_100 = "<:booster_100:1509785418235908168>"

# Prestige role emojis
PRESTIGE_EMOJIS = {
    1: "<:Prestige_1:1510526680954048654>",
    2: "<:Prestige_2:1510526711605760000>",
    3: "<:Prestige_3:1510526740303319100>",
    4: "<:Prestige_4:1510526767369158806>",
    5: "<:Prestige_5:1510526802295001178>",
    6: "<:Prestige_6:1510526835455426621>",
    7: "<:Prestige_7:1510526870079410227>",
    8: "<:Prestige_8:1510526899749916802>",
    9: "<:Prestige_9:1510526930254954566>",
    10: "<:Prestige_10:1510526952363262052>",
}

# Level role emojis
LEVEL_EMOJIS = {
    5:   "<:Level_5:1510527002149392384>",
    10:  "<:Level_10:1510527030863724584>",
    20:  "<:Level_20:1510527058206261329>",
    30:  "<:Level_30:1510527089080795199>",
    40:  "<:Level_40:1510527119816655000>",
    45:  "<:Level_45:1510527147377430658>",
    50:  "<:Level_50:1510527177769091144>",
    60:  "<:Level_60:1510527209926955109>",
    70:  "<:Level_70:1510527306903588914>",
    80:  "<:Level_80:1510527330026782740>",
    90:  "<:Level_90:1510527354642890833>",
    100: "<:Level_100:1510527377493463101>",
}

# Level role colors (gradient / flat)
LEVEL_GRADIENT_COLORS = {
    5:   ("#6B6B7A", "#1A1A22"),
    10:  ("#EEF9FF", "#A9C8E8"),
    20:  ("#FFDFF3", "#FF7BC7"),
    30:  ("#FF8AD9", "#EA3DA7"),
    40:  ("#D65BBE", "#9B1A8F"),
    45:  ("#C997FF", "#7A3FE0"),
    50:  ("#B87CFF", "#5B19D6"),
    60:  ("#8F92FF", "#4A3DDA"),
    70:  ("#5DA2FF", "#0D4ED6"),
    80:  ("#6CD7FF", "#008EE6"),
    90:  ("#9DE4FF", "#3AB8FF"),
    100: ("#64F3F1", "#00BFCF"),
}
LEVEL_FLAT_COLORS = {
    5:   0x2E2E36,
    10:  0xCDE4F8,
    20:  0xFFB6E4,
    30:  0xFF4DB8,
    40:  0xB726A0,
    45:  0xA768F5,
    50:  0x7A34E1,
    60:  0x5D63F2,
    70:  0x1E62E4,
    80:  0x19A6EA,
    90:  0x63C7FF,
    100: 0x1FD6D3,
}
PRESTIGE_GRADIENT_COLORS = {
    1:  ("#4FE7D2", "#1FA9C5"),
    2:  ("#8C5A34", "#D8B08A"),
    3:  ("#FFD45A", "#D89A22"),
    4:  ("#FF8A9A", "#E05060"),
    5:  ("#E9D17A", "#A88A2D"),
    6:  ("#F8A2E8", "#B764C5"),
    7:  ("#6FA6FF", "#315DC9"),
    8:  ("#63E07C", "#249E49"),
    9:  ("#FF7465", "#D82C1E"),
    10: ("#FF9AD9", "#F04DB3"),
}
PRESTIGE_FLAT_COLORS = {
    1:  0x4FE7D2,
    2:  0x8C5A34,
    3:  0xFFD45A,
    4:  0xFF8A9A,
    5:  0xE9D17A,
    6:  0xF8A2E8,
    7:  0x6FA6FF,
    8:  0x63E07C,
    9:  0xFF7465,
    10: 0xFF9AD9,
}

# Milestone definitions
MILESTONES = [
    (5,   EMOJI_LVL_NICK,    "Ability to edit your Nickname",          "change_nickname"),
    (10,  EMOJI_LVL_EMOTES,  "Use External Emotes",                    "external_emojis"),
    (20,  EMOJI_LVL_STREAM,  "Unlock Streaming and Camera",            "stream"),
    (30,  EMOJI_LVL_VOICE,   "Unlock Voice Messages",                  "send_voice_messages"),
    (40,  EMOJI_LVL_SOUND,   "Unlock Soundboard",                      "use_soundboard"),
    (45,  EMOJI_LVL_POLLS,   "Unlock Polls",                           "send_polls"),
    (50,  EMOJI_LVL_IMAGE,   "Post Images Anywhere",                   "attach_files"),
    (60,  EMOJI_LVL_EXTSND,  "Access to External Sounds",              "use_external_sounds"),
    (70,  EMOJI_LVL_BOOST,   "5 Extra Boost daily",                    None),
    (80,  EMOJI_LVL_2XP,     "2x multiplier",                          None),
    (90,  EMOJI_LVL_THREADS, "Ability to create Threads",              "create_public_threads"),
    (100, EMOJI_LVL_PRESTIGE,"Unlock Prestige",                        None),
]

MILESTONE_LEVELS = [m[0] for m in MILESTONES]

XP_EARN_CAP = 200_000

# ---------- DB Init (leveling tables) ----------
def init_lvl_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_config (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            xp_channel_ids TEXT DEFAULT '',
            lvlup_channel_ids TEXT DEFAULT '',
            vote_time TEXT DEFAULT '',
            vote_reward_credits INTEGER DEFAULT 0,
            vote_link TEXT DEFAULT '',
            winner_channel_id INTEGER DEFAULT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_users (
            user_id INTEGER,
            guild_id INTEGER,
            xp INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            prestige INTEGER DEFAULT 0,
            credits INTEGER DEFAULT 0,
            multiplier INTEGER DEFAULT 0,
            last_chat_xp TIMESTAMP,
            reactions_enabled INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, guild_id)
        )''')
        try:
            conn.execute("ALTER TABLE lvl_users ADD COLUMN reactions_enabled INTEGER DEFAULT 1")
        except Exception:
            pass
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_boosters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            guild_id INTEGER,
            booster_type TEXT,
            pct INTEGER,
            expires_at TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_booster_inv (
            user_id INTEGER,
            guild_id INTEGER,
            booster_type TEXT,
            quantity INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, booster_type)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_level_roles (
            guild_id INTEGER,
            level INTEGER,
            role_id INTEGER,
            PRIMARY KEY (guild_id, level)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_prestige_roles (
            guild_id INTEGER,
            prestige INTEGER,
            role_id INTEGER,
            PRIMARY KEY (guild_id, prestige)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_blessings (
            user_id INTEGER,
            guild_id INTEGER,
            blessing_type TEXT,
            multiplier INTEGER,
            expires_at TIMESTAMP,
            PRIMARY KEY (user_id, guild_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_bless_daily (
            user_id INTEGER,
            guild_id INTEGER,
            bless_type TEXT,
            used INTEGER DEFAULT 0,
            last_reset TIMESTAMP,
            PRIMARY KEY (user_id, guild_id, bless_type)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_vip_roles (
            user_id INTEGER,
            guild_id INTEGER,
            tier TEXT,
            expires_at TIMESTAMP,
            PRIMARY KEY (user_id, guild_id, tier)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_discord_roles (
            guild_id INTEGER,
            tier TEXT,
            role_id INTEGER,
            PRIMARY KEY (guild_id, tier)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_reactions (
            user_id INTEGER,
            guild_id INTEGER,
            emoji TEXT,
            PRIMARY KEY (user_id, guild_id, emoji)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_vc_sessions (
            user_id INTEGER,
            guild_id INTEGER,
            joined_at TIMESTAMP,
            PRIMARY KEY (user_id, guild_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_vc_time (
            user_id INTEGER,
            guild_id INTEGER,
            total_minutes INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_votes (
            user_id INTEGER,
            guild_id INTEGER,
            voted_at TIMESTAMP,
            rewarded INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, voted_at)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_big_boosters (
            user_id INTEGER,
            guild_id INTEGER,
            booster_type TEXT,
            quantity INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, booster_type)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_active_big_booster (
            user_id INTEGER,
            guild_id INTEGER,
            booster_type TEXT,
            multiplier INTEGER,
            expires_at TIMESTAMP,
            PRIMARY KEY (user_id, guild_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lvl_boost_daily (
            user_id INTEGER,
            guild_id INTEGER,
            used INTEGER DEFAULT 0,
            last_reset TIMESTAMP,
            PRIMARY KEY (user_id, guild_id)
        )''')
        conn.commit()

init_lvl_db()

# ---------- XP Formula ----------
def xp_for_level(level: int, prestige: int = 0) -> int:
    """XP required to reach `level` from 0."""
    base = round(100 * (level ** 1.5))
    multiplier = 1.0 + prestige * 0.1
    return round(base * multiplier)

def total_xp_for_level(level: int, prestige: int = 0) -> int:
    """Total cumulative XP needed to reach this level."""
    return sum(xp_for_level(l, prestige) for l in range(1, level + 1))

# ---------- Leveling Helpers ----------
def get_lvl_config(guild_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM lvl_config WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return {"guild_id": guild_id, "enabled": 0, "xp_channel_ids": "",
                    "lvlup_channel_ids": "", "vote_time": "", "vote_reward_credits": 0, "vote_link": "",
                    "winner_channel_id": None}
        cols = ["guild_id","enabled","xp_channel_ids","lvlup_channel_ids","vote_time","vote_reward_credits","vote_link","winner_channel_id"]
        return dict(zip(cols, row))

def ensure_lvl_config(guild_id: int):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO lvl_config (guild_id) VALUES (?)", (guild_id,))
        conn.commit()

def get_lvl_user(user_id: int, guild_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM lvl_users WHERE user_id=? AND guild_id=?", (user_id, guild_id)).fetchone()
        if not row:
            return {"user_id": user_id, "guild_id": guild_id, "xp": 0, "total_earned": 0,
                    "level": 0, "prestige": 0, "credits": 0, "multiplier": 0, "last_chat_xp": None,
                    "reactions_enabled": 1}
        cols = ["user_id","guild_id","xp","total_earned","level","prestige","credits","multiplier","last_chat_xp","reactions_enabled"]
        return dict(zip(cols, row))

def ensure_lvl_user(user_id: int, guild_id: int):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO lvl_users (user_id, guild_id) VALUES (?,?)", (user_id, guild_id))
        conn.commit()

def get_effective_multiplier(user_id: int, guild_id: int) -> float:
    """Returns total XP multiplier from all sources."""
    now = datetime.now(timezone.utc)
    mult = 1.0
    with get_db() as conn:
        # Percent boosters
        rows = conn.execute(
            "SELECT pct FROM lvl_boosters WHERE user_id=? AND guild_id=? AND expires_at > ?",
            (user_id, guild_id, now)
        ).fetchall()
        for (pct,) in rows:
            mult += pct / 100.0

        # Big boosters (double/triple/5x)
        row = conn.execute(
            "SELECT multiplier FROM lvl_active_big_booster WHERE user_id=? AND guild_id=? AND expires_at > ?",
            (user_id, guild_id, now)
        ).fetchone()
        if row:
            mult += row[0] - 1  # e.g. 2x adds +1.0

        # Blessing
        brow = conn.execute(
            "SELECT multiplier FROM lvl_blessings WHERE user_id=? AND guild_id=? AND expires_at > ?",
            (user_id, guild_id, now)
        ).fetchone()
        if brow:
            mult += brow[0] - 1

        # VIP/Elite/Supreme XP bonus
        tiers = conn.execute(
            "SELECT tier FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND expires_at > ?",
            (user_id, guild_id, now)
        ).fetchall()
        for (tier,) in tiers:
            if tier == "supreme":
                mult += 3.0
            elif tier == "elite":
                mult += 2.0
            elif tier == "vip":
                mult += 1.5

        # Level 80 milestone: +2x (adds 1.0)
        udata = conn.execute("SELECT level FROM lvl_users WHERE user_id=? AND guild_id=?", (user_id, guild_id)).fetchone()
        if udata and udata[0] >= 80:
            mult += 1.0

    return mult

async def grant_level_role(guild: discord.Guild, member: discord.Member, level: int):
    """Create level role if not exists, grant to member."""
    with get_db() as conn:
        row = conn.execute("SELECT role_id FROM lvl_level_roles WHERE guild_id=? AND level=?", (guild.id, level)).fetchone()
        if row:
            role = guild.get_role(row[0])
            if not role:
                row = None
        if not row:
            color_int = LEVEL_FLAT_COLORS.get(level, 0x99aab5)
            try:
                role = await guild.create_role(name=f"Level {level}", color=discord.Color(color_int), reason="Level milestone")
                # Apply gradient if available
                if guild.premium_tier >= 3 and level in LEVEL_GRADIENT_COLORS:
                    c1, c2 = LEVEL_GRADIENT_COLORS[level]
                    try:
                        await _apply_gradient_to_role(role, hex_to_int(c1[1:]), hex_to_int(c2[1:]))
                    except Exception:
                        pass
                # Apply icon if available
                if guild.premium_tier >= 2 and level in LEVEL_EMOJIS:
                    emoji_str = LEVEL_EMOJIS[level]
                    icon_url = emoji_to_url(emoji_str)
                    if icon_url:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(icon_url) as resp:
                                    if resp.status == 200:
                                        raw = await resp.read()
                                        img = _process_icon_bytes(raw)
                                        await role.edit(icon=img)
                        except Exception:
                            pass
            except discord.Forbidden:
                return
            with get_db() as c2:
                c2.execute("INSERT OR REPLACE INTO lvl_level_roles (guild_id, level, role_id) VALUES (?,?,?)",
                           (guild.id, level, role.id))
                c2.commit()
        else:
            role = guild.get_role(row[0])
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason=f"Reached Level {level}")
        except discord.Forbidden:
            pass

    # Grant milestone permissions
    if role:
        for mlvl, _, _, perm_name in MILESTONES:
            if mlvl == level and perm_name:
                try:
                    perms = role.permissions
                    setattr(perms, perm_name, True)
                    await role.edit(permissions=perms)
                except Exception:
                    pass

async def grant_prestige_role(guild: discord.Guild, member: discord.Member, prestige: int):
    with get_db() as conn:
        row = conn.execute("SELECT role_id FROM lvl_prestige_roles WHERE guild_id=? AND prestige=?", (guild.id, prestige)).fetchone()
        role = guild.get_role(row[0]) if row else None
        if not role:
            color_int = PRESTIGE_FLAT_COLORS.get(prestige, 0x99aab5)
            try:
                role = await guild.create_role(name=f"Prestige {prestige}", color=discord.Color(color_int), reason="Prestige unlock")
                if guild.premium_tier >= 3 and prestige in PRESTIGE_GRADIENT_COLORS:
                    c1, c2 = PRESTIGE_GRADIENT_COLORS[prestige]
                    try:
                        await _apply_gradient_to_role(role, hex_to_int(c1[1:]), hex_to_int(c2[1:]))
                    except Exception:
                        pass
                if guild.premium_tier >= 2 and prestige in PRESTIGE_EMOJIS:
                    emoji_str = PRESTIGE_EMOJIS[prestige]
                    icon_url = emoji_to_url(emoji_str)
                    if icon_url:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(icon_url) as resp:
                                    if resp.status == 200:
                                        raw = await resp.read()
                                        img = _process_icon_bytes(raw)
                                        await role.edit(icon=img)
                        except Exception:
                            pass
            except discord.Forbidden:
                return
            with get_db() as c2:
                c2.execute("INSERT OR REPLACE INTO lvl_prestige_roles (guild_id, prestige, role_id) VALUES (?,?,?)",
                           (guild.id, prestige, role.id))
                c2.commit()
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason=f"Prestige {prestige}")
        except discord.Forbidden:
            pass

async def process_level_up(bot_instance, guild: discord.Guild, member: discord.Member, old_level: int, new_level: int, reward_desc: str):
    """Send level-up embed and grant roles."""
    cfg = get_lvl_config(guild.id)
    channel = None
    if cfg["lvlup_channel_ids"]:
        for cid in cfg["lvlup_channel_ids"].split(","):
            cid = cid.strip()
            if cid.isdigit():
                ch = guild.get_channel(int(cid))
                if ch:
                    channel = ch
                    break
    if not channel:
        channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
    if not channel:
        return

    embed = discord.Embed(color=discord.Color.blurple())
    embed.description = (
        f"\u200b\n"
        f"{EMOJI_LVL_INFO} You **__leveled__** up {old_level} {EMOJI_LVL_INCREASE} to **Level {new_level}**!\n"
        f"\u200b\n"
        f"{EMOJI_LVL_REWARD} **__Reward__**\n"
        f"`-` {reward_desc}\n"
        f"\u200b\n"
        f"{EMOJI_LVL_CHAT} Stay **__active__** in **__chat or calls__** to keep earning **XP** {EMOJI_LVL_XP}"
    )
    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    await channel.send(content=member.mention, embed=embed)

    if new_level in MILESTONE_LEVELS:
        await grant_level_role(guild, member, new_level)
        if new_level == 70:
            # Level 70 milestone: 5 extra daily boosts
            await add_user_extra_votes(member.id, guild.id, 5)

async def add_xp(bot_instance, guild: discord.Guild, member: discord.Member, base_xp: int, source: str = "chat"):
    """Add XP to a user, handle level ups."""
    ensure_lvl_user(member.id, guild.id)
    udata = get_lvl_user(member.id, guild.id)

    # Cap earned XP
    if udata["total_earned"] >= XP_EARN_CAP and source in ("chat", "vc"):
        return

    mult = get_effective_multiplier(member.id, guild.id)
    gained = max(1, round(base_xp * mult))

    if source in ("chat", "vc"):
        can_earn = XP_EARN_CAP - udata["total_earned"]
        gained = min(gained, can_earn)

    new_total_earned = udata["total_earned"] + (gained if source in ("chat", "vc") else 0)
    new_xp = udata["xp"] + gained
    old_level = udata["level"]
    prestige = udata["prestige"]

    # Check level ups — hard cap at 100, prestige requires manual !prestige command
    new_level = old_level
    while True:
        if new_level >= 100:
            # Hold at 100, don't overflow XP
            new_level = 100
            new_xp = 0
            break
        needed = xp_for_level(new_level + 1, prestige)
        if new_xp >= needed:
            new_xp -= needed
            new_level += 1
        else:
            break

    with get_db() as conn:
        conn.execute(
            "UPDATE lvl_users SET xp=?, total_earned=?, level=? WHERE user_id=? AND guild_id=?",
            (new_xp, new_total_earned, new_level, member.id, guild.id)
        )
        conn.commit()

    if new_level > old_level:
        reward_desc = await _generate_level_reward(member.id, guild.id, new_level)
        await process_level_up(bot_instance, guild, member, old_level, new_level, reward_desc)

async def _generate_level_reward(user_id: int, guild_id: int, level: int) -> str:
    """Pick a random reward, apply it, return display string."""
    roll = random.random()
    if roll < 0.33:
        # Credits
        amount = random.randint(10, 100)
        with get_db() as conn:
            conn.execute("UPDATE lvl_users SET credits = credits + ? WHERE user_id=? AND guild_id=?",
                         (amount, user_id, guild_id))
            conn.commit()
        return f"{EMOJI_LVL_CREDITS} **{amount}** Credits"
    elif roll < 0.66:
        # XP Booster
        booster_types = [
            (EMOJI_BOOST_10, "10%", 10, 1),
            (EMOJI_BOOST_25, "25%", 25, 1),
            (EMOJI_BOOST_50, "50%", 50, 1),
            (EMOJI_BOOST_75, "75%", 75, 1),
            (EMOJI_BOOST_100, "100%", 100, 1),
        ]
        emoji, label, pct, hours = random.choice(booster_types)
        btype = f"pct_{pct}"
        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO lvl_booster_inv (user_id, guild_id, booster_type, quantity) VALUES (?,?,?,0)",
                (user_id, guild_id, btype)
            )
            conn.execute(
                "UPDATE lvl_booster_inv SET quantity = quantity + 1 WHERE user_id=? AND guild_id=? AND booster_type=?",
                (user_id, guild_id, btype)
            )
            conn.commit()
        return f"{emoji} **{label} XP Booster** (1h)"
    else:
        # Random multiplier bonus — temporary (30–50 minutes)
        bonus = random.randint(20, 100)
        duration_mins = random.randint(30, 50)
        expires = datetime.now(timezone.utc) + timedelta(minutes=duration_mins)
        btype = f"bonus_{bonus}"
        with get_db() as conn:
            conn.execute(
                "INSERT INTO lvl_boosters (user_id, guild_id, booster_type, pct, expires_at) VALUES (?,?,?,?,?)",
                (user_id, guild_id, btype, bonus, expires)
            )
            conn.commit()
        return f"{EMOJI_LVL_USER_XP} **+{bonus}% bonus XP** ({duration_mins}m)"

# ---------- Progress Embed Builder ----------
def build_progress_embed(member: discord.Member, udata: dict, guild_id: int) -> discord.Embed:
    level = udata["level"]
    prestige = udata["prestige"]
    xp = udata["xp"]
    needed = xp_for_level(level + 1, prestige)
    left = needed - xp
    mult = get_effective_multiplier(member.id, guild_id)

    # Build milestones
    milestone_lines = []
    for mlvl, emoji, desc, _ in MILESTONES:
        icon = EMOJI_LVL_UNLOCKED if level >= mlvl else EMOJI_LVL_LOCKED
        milestone_lines.append(f"{icon} **Level {mlvl} |** {emoji} {desc}")

    milestone_text = "\n".join(milestone_lines)
    mult_display = f"{mult:.2f}x multiplier"

    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_author(name=f"{member.display_name}'s Progress", icon_url=member.avatar.url if member.avatar else None)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    embed.description = (
        f"\u200b\n"
        f"{EMOJI_LVL_LEVEL} **Level {level}** ({mult_display})\n"
        f"\u200b\n"
        f"{EMOJI_LVL_INFO} **XP Progress**\n"
        f"{EMOJI_LVL_EXTEND} **{xp:,}/{needed:,}** {EMOJI_LVL_XP}\n"
        f"\u200b\n"
        f"{EMOJI_LVL_ROCKET} **__Milestones__**\n"
        f"{milestone_text}\n"
        f"\u200b\n"
        f"Keep up the activity in VC/Chat to gain XP and unlock new milestones!"
    )
    if prestige > 0:
        embed.add_field(name="Prestige", value=f"**{prestige}** {PRESTIGE_EMOJIS.get(prestige, '')}", inline=True)
    return embed

def build_booster_embed(member: discord.Member, guild_id: int) -> discord.Embed:
    now = datetime.now(timezone.utc)
    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_author(name=f"{member.display_name}'s Boosters", icon_url=member.avatar.url if member.avatar else None)
    embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1509751861228474438.png")

    with get_db() as conn:
        active = conn.execute(
            "SELECT booster_type, pct, expires_at FROM lvl_boosters WHERE user_id=? AND guild_id=? AND expires_at > ? ORDER BY expires_at ASC",
            (member.id, guild_id, now)
        ).fetchall()
        inv = conn.execute(
            "SELECT booster_type, quantity FROM lvl_booster_inv WHERE user_id=? AND guild_id=? AND quantity > 0",
            (member.id, guild_id)
        ).fetchall()
        big_active = conn.execute(
            "SELECT booster_type, multiplier, expires_at FROM lvl_active_big_booster WHERE user_id=? AND guild_id=? AND expires_at > ?",
            (member.id, guild_id, now)
        ).fetchone()
        big_inv = conn.execute(
            "SELECT booster_type, quantity FROM lvl_big_boosters WHERE user_id=? AND guild_id=? AND quantity > 0",
            (member.id, guild_id)
        ).fetchall()

    # Helper to format remaining time
    def format_remaining(expires_at):
        delta = expires_at - now
        total_sec = int(delta.total_seconds())
        if total_sec <= 0:
            return "Expired"
        if total_sec >= 3600:
            hours = total_sec // 3600
            return f"{hours}h"
        elif total_sec >= 60:
            minutes = total_sec // 60
            return f"{minutes}m"
        else:
            return f"{total_sec}s"

    BOOSTER_DISPLAY = {
        "pct_10": f"{EMOJI_BOOST_10} 10% XP Booster",
        "pct_25": f"{EMOJI_BOOST_25} 25% XP Booster",
        "pct_50": f"{EMOJI_BOOST_50} 50% XP Booster",
        "pct_75": f"{EMOJI_BOOST_75} 75% XP Booster",
        "pct_100": f"{EMOJI_BOOST_100} 100% XP Booster",
        "double": f"{EMOJI_LVL_DOUBLE} Double XP",
        "dbl_1h": f"{EMOJI_LVL_DOUBLE} Double XP",
        "dbl_12h": f"{EMOJI_LVL_DOUBLE} Double XP",
        "dbl_24h": f"{EMOJI_LVL_DOUBLE} Double XP",
        "triple": f"{EMOJI_LVL_TRIPLE} Triple XP",
        "tri_1h": f"{EMOJI_LVL_TRIPLE} Triple XP",
        "tri_12h": f"{EMOJI_LVL_TRIPLE} Triple XP",
        "tri_24h": f"{EMOJI_LVL_TRIPLE} Triple XP",
        "5x": f"{EMOJI_LVL_5X} 5x XP",
        "5x_24h": f"{EMOJI_LVL_5X} 5x XP",
        "5x_3d": f"{EMOJI_LVL_5X} 5x XP",
    }

    # Active section
    active_lines = []
    if active:
        for btype, pct, exp in active:
            if btype.startswith("bonus_") or btype.startswith("extend_"):
                continue
            label = BOOSTER_DISPLAY.get(btype, f"{pct}% XP Booster")
            time_left = format_remaining(exp)
            active_lines.append(f"{label} expires in **{time_left}**")
    if big_active:
        label = BOOSTER_DISPLAY.get(big_active[0], f"{big_active[0].capitalize()} XP")
        time_left = format_remaining(big_active[2])
        active_lines.append(f"{label} expires in **{time_left}**")
    active_text = "\n".join(active_lines) if active_lines else "❌ None"

    # Inventory
    inv_lines = []
    for btype, qty in inv:
        label = BOOSTER_DISPLAY.get(btype, btype)
        inv_lines.append(f"{label} **({qty}x)**")
    for btype, qty in big_inv:
        label = BOOSTER_DISPLAY.get(btype, btype)
        inv_lines.append(f"{label} **({qty}x)**")
    inv_text = "\n".join(inv_lines) if inv_lines else "No boosters in inventory."

    embed.description = (
        f"__**Activated**__\n{active_text}\n\n"
        f"__**Boosters**__\n{inv_text}"
    )
    return embed

def build_credits_embed(member: discord.Member, guild_id: int) -> discord.Embed:
    udata = get_lvl_user(member.id, guild_id)
    credits = udata["credits"]
    embed = discord.Embed(color=discord.Color.gold())
    embed.set_author(name=f"{member.display_name}'s Credits", icon_url=member.avatar.url if member.avatar else None)
    embed.description = (
        f"You have **{credits:,}** {EMOJI_LVL_CREDITS} credits left\n\n"
        f"{EMOJI_LVL_DOUBLE} Double XP Booster [1 day] — **250 credits**\n"
        f"{EMOJI_LVL_VIP} VIP [30 days] — **1,000 credits**\n"
        f"{EMOJI_LVL_ELITE} Elite [30 days] — **2,000 credits**\n"
        f"{EMOJI_LVL_SUPREME} Supreme [30 days] — **10,000 credits**"
    )
    return embed

def build_compact_lvl_embed(member: discord.Member, udata: dict, guild_id: int) -> discord.Embed:
    """Compact level card shown by !lvl — mirrors the screenshot style."""
    level = udata["level"]
    prestige = udata["prestige"]
    xp = udata["xp"]
    needed = xp_for_level(level + 1, prestige)
    left = needed - xp

    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_author(
        name=f"{member.display_name}'s Level",
        icon_url=member.avatar.url if member.avatar else None
    )
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    prestige_str = f"Prestige {prestige}" if prestige > 0 else "Prestige 0"
    embed.description = (
        f"**{prestige_str} | Level {level}**\n\n"
        f"{EMOJI_LVL_PROGRESS} **Progress**\n"
        f"{xp:,}/{needed:,} ({left:,})"
    )
    return embed


def build_leaderboard_embed(guild: discord.Guild) -> discord.Embed:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT user_id, total_minutes FROM lvl_vc_time WHERE guild_id=? ORDER BY total_minutes DESC LIMIT 10",
            (guild.id,)
        ).fetchall()
    embed = discord.Embed(title=f"🎙️ VC Leaderboard — {guild.name}", color=discord.Color.blurple())
    lines = []
    for i, (uid, mins) in enumerate(rows, 1):
        m = guild.get_member(uid)
        name = m.mention if m else f"`{uid}`"
        lines.append(f"**#{i} {name}** active for **{mins}** minutes")
    embed.description = "\n".join(lines) if lines else "No VC activity yet."
    return embed

def build_vote_embed(guild: discord.Guild, cfg: dict) -> discord.Embed:
    link = cfg.get("vote_link", "") or "*(not configured)*"
    credits_reward = cfg.get("vote_reward_credits", 0)
    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_author(name=f"Voting — {guild.name}")
    embed.description = (
        f"Voting for **{guild.name}** will get you rewards:\n\n"
        f"**25% XP** (12h)\n"
        f"**{credits_reward}** {EMOJI_LVL_CREDITS} Credits\n\n"
        f"🔗 [Vote here]({link})"
    )
    return embed

# ---------- Back-only sub-page view ----------
class BackOnlyView(DisableOnTimeoutView):
    """Single Back button — returns to the progress page of the parent LvlView."""
    def __init__(self, member, guild, lvl_view):
        super().__init__(timeout=120)
        self.member = member
        self.guild = guild
        self.lvl_view = lvl_view

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
        async def back_cb(interaction: discord.Interaction):
            ensure_lvl_user(self.member.id, self.guild.id)
            udata = get_lvl_user(self.member.id, self.guild.id)
            embed = build_progress_embed(self.member, udata, self.guild.id)
            await interaction.response.edit_message(embed=embed, view=self.lvl_view)
        back_btn.callback = back_cb
        self.add_item(back_btn)


# ---------- !lvl View (5 buttons) ----------
class LvlView(DisableOnTimeoutView):
    def __init__(self, member: discord.Member, guild: discord.Guild, page: str = "progress"):
        super().__init__(timeout=120)
        self.member = member
        self.guild = guild
        self.page = page

    async def _render(self, interaction: discord.Interaction, page: str):
        self.page = page
        udata = get_lvl_user(self.member.id, self.guild.id)
        cfg = get_lvl_config(self.guild.id)
        if page == "progress":
            embed = build_progress_embed(self.member, udata, self.guild.id)
        elif page == "booster":
            embed = build_booster_embed(self.member, self.guild.id)
        elif page == "credits":
            embed = build_credits_embed(self.member, self.guild.id)
        elif page == "leaderboard":
            embed = build_leaderboard_embed(self.guild)
        elif page == "vote":
            embed = build_vote_embed(self.guild, cfg)
        else:
            embed = build_progress_embed(self.member, udata, self.guild.id)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Progress", style=discord.ButtonStyle.primary, emoji=EMOJI_LVL_PROGRESS, row=0)
    async def progress_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._render(interaction, "progress")

    @discord.ui.button(label="Booster", style=discord.ButtonStyle.success, emoji=EMOJI_LVL_BOOSTERS, row=0)
    async def booster_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_booster_embed(self.member, self.guild.id)
        # Build booster select options
        now = datetime.now(timezone.utc)
        with get_db() as conn:
            inv = conn.execute(
                "SELECT booster_type, quantity FROM lvl_booster_inv WHERE user_id=? AND guild_id=? AND quantity > 0",
                (self.member.id, self.guild.id)
            ).fetchall()
            big_inv = conn.execute(
                "SELECT booster_type, quantity FROM lvl_big_boosters WHERE user_id=? AND guild_id=? AND quantity > 0",
                (self.member.id, self.guild.id)
            ).fetchall()
        options = []
        BOOSTER_LABELS = {
    "pct_10": "10% XP Booster [1 hour]",
    "pct_25": "25% XP Booster [1 hour]",
    "pct_50": "50% XP Booster [1 hour]",
    "pct_75": "75% XP Booster [1 hour]",
    "pct_100": "100% XP Booster [1 hour]",
    "dbl_1h": "Double XP [1 hour]",
    "dbl_12h": "Double XP [12 hours]",
    "dbl_24h": "Double XP [24 hours]",
    "tri_1h": "Triple XP [1 hour]",
    "tri_12h": "Triple XP [12 hours]",
    "tri_24h": "Triple XP [24 hours]",
    "5x_24h": "5x XP [24 hours]",
    "5x_3d": "5x XP [3 days]",
}
        for btype, qty in list(inv) + list(big_inv):
            label = BOOSTER_LABELS.get(btype, btype)
            options.append(discord.SelectOption(label=f"{label} ({qty}x)", value=btype))

        if options:
            view = BoosterSelectView(self.member, self.guild, options, self)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=BackOnlyView(self.member, self.guild, self))

    @discord.ui.button(label="Credits", style=discord.ButtonStyle.success, emoji=EMOJI_LVL_CREDITS, row=0)
    async def credits_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_credits_embed(self.member, self.guild.id)
        view = CreditsShopView(self.member, self.guild, self)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Leaderboard", style=discord.ButtonStyle.secondary, emoji=EMOJI_LVL_BOOST, row=1)
    async def lb_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_leaderboard_embed(self.guild)
        await interaction.response.edit_message(embed=embed, view=BackOnlyView(self.member, self.guild, self))

    @discord.ui.button(label="Vote", style=discord.ButtonStyle.secondary, emoji="🗳️", row=1)
    async def vote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_lvl_config(self.guild.id)
        embed = build_vote_embed(self.guild, cfg)
        await interaction.response.edit_message(embed=embed, view=BackOnlyView(self.member, self.guild, self))

class BoosterSelectView(DisableOnTimeoutView):
    def __init__(self, member, guild, options, lvl_view):
        super().__init__(timeout=60)
        self.member = member
        self.guild = guild
        self.lvl_view = lvl_view  # original LvlView (may time out later, but we'll create fresh when needed)

        BOOSTER_LABELS = {
            "pct_10": "10% XP Boost", "pct_25": "25% XP Boost",
            "pct_50": "50% XP Boost", "pct_75": "75% XP Boost",
            "pct_100": "100% XP Boost",
            "dbl_1h": "Double XP", "dbl_12h": "Double XP", "dbl_24h": "Double XP",
            "tri_1h": "Triple XP", "tri_12h": "Triple XP", "tri_24h": "Triple XP",
            "5x_24h": "5x XP", "5x_3d": "5x XP",
        }
        EMOJI_MAP = {
            "pct_10": EMOJI_BOOST_10, "pct_25": EMOJI_BOOST_25,
            "pct_50": EMOJI_BOOST_50, "pct_75": EMOJI_BOOST_75,
            "pct_100": EMOJI_BOOST_100,
            "dbl_1h": EMOJI_LVL_DOUBLE, "dbl_12h": EMOJI_LVL_DOUBLE, "dbl_24h": EMOJI_LVL_DOUBLE,
            "tri_1h": EMOJI_LVL_TRIPLE, "tri_12h": EMOJI_LVL_TRIPLE, "tri_24h": EMOJI_LVL_TRIPLE,
            "5x_24h": EMOJI_LVL_5X, "5x_3d": EMOJI_LVL_5X,
        }

        new_options = []
        for opt in options:
            btype = opt.value
            label = BOOSTER_LABELS.get(btype, btype)
            emoji = EMOJI_MAP.get(btype)
            new_options.append(discord.SelectOption(label=label, value=btype, emoji=emoji, description=opt.description))
        select = discord.ui.Select(placeholder="Select a booster...", options=new_options)

        async def select_cb(interaction: discord.Interaction):
            btype = select.values[0]
            bname = BOOSTER_LABELS.get(btype, btype)
            emoji = EMOJI_MAP.get(btype, "⭐")
            with get_db() as conn:
                qty = conn.execute(
                    "SELECT quantity FROM lvl_booster_inv WHERE user_id=? AND guild_id=? AND booster_type=?",
                    (self.member.id, self.guild.id, btype)
                ).fetchone()
                if not qty:
                    qty = conn.execute(
                        "SELECT quantity FROM lvl_big_boosters WHERE user_id=? AND guild_id=? AND booster_type=?",
                        (self.member.id, self.guild.id, btype)
                    ).fetchone()
            available = qty[0] if qty else 0
            if available <= 0:
                await interaction.response.send_message("You don't have that booster.", ephemeral=True)
                return

            if available == 1:
                view = BoosterConfirmSimpleView(self.member, self.guild, btype, bname, emoji, available, self.lvl_view)
                await view.update_display(interaction)
            else:
                view = BoosterQuantityView(self.member, self.guild, btype, bname, emoji, available, self.lvl_view)
                await view.update_display(interaction)

        select.callback = select_cb
        self.add_item(select)

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
        async def back_cb(interaction: discord.Interaction):
            # Create a fresh LvlView to avoid timeout issues
            fresh_lvl_view = LvlView(self.member, self.guild, "progress")
            udata = get_lvl_user(self.member.id, self.guild.id)
            embed = build_progress_embed(self.member, udata, self.guild.id)
            await interaction.response.edit_message(embed=embed, view=fresh_lvl_view)
        back_btn.callback = back_cb
        self.add_item(back_btn)


class BoosterConfirmSimpleView(DisableOnTimeoutView):
    """For when only 1 booster is available – no quantity pad."""
    def __init__(self, member, guild, btype, bname, emoji, available, lvl_view):
        super().__init__(timeout=60)
        self.member = member
        self.guild = guild
        self.btype = btype
        self.bname = bname
        self.emoji = emoji
        self.available = available
        self.original_lvl_view = lvl_view
        self.active_duration = None

        self.confirm_btn = discord.ui.Button(label="Use", style=discord.ButtonStyle.success, row=0)
        self.confirm_btn.callback = self.confirm_callback
        self.add_item(self.confirm_btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=BTN_BACK, row=0)
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)

    async def update_display(self, interaction: discord.Interaction):
        now = datetime.now(timezone.utc)
        PCT_MAP = {"pct_10": 10, "pct_25": 25, "pct_50": 50, "pct_75": 75, "pct_100": 100}
        BIG_MAP = {
            "dbl_1h": (2, 1), "dbl_12h": (2, 12), "dbl_24h": (2, 24),
            "tri_1h": (3, 1), "tri_12h": (3, 12), "tri_24h": (3, 24),
            "5x_24h": (5, 24), "5x_3d": (5, 72),
        }

        if self.btype in PCT_MAP:
            pct = PCT_MAP[self.btype]
            gain = f"+{pct}% XP"
            base_hours = 1
            total_hours = base_hours
            duration_str = "1 hour"
            with get_db() as conn:
                active = conn.execute(
                    "SELECT expires_at FROM lvl_boosters WHERE user_id=? AND guild_id=? AND booster_type=? AND expires_at > ?",
                    (self.member.id, self.guild.id, self.btype, now)
                ).fetchone()
            if active:
                remaining = active[0] - now
                remaining_hours = remaining.total_seconds() / 3600
                self.active_duration = remaining_hours
                self.confirm_btn.label = "Extend"
                self.confirm_btn.style = discord.ButtonStyle.primary
                extra_text = f"\n\n⚠️ You already have an active **{self.bname}** with **{remaining_hours:.1f} hours** left.\nUsing this will **extend** it by {duration_str}."
            else:
                self.active_duration = None
                self.confirm_btn.label = "Use"
                self.confirm_btn.style = discord.ButtonStyle.success
                extra_text = ""
        elif self.btype in BIG_MAP:
            mult, base_hours = BIG_MAP[self.btype]
            gain = f"{mult}x XP"
            total_hours = base_hours
            if total_hours >= 24:
                days = total_hours // 24
                duration_str = f"{days} day{'s' if days != 1 else ''}"
            else:
                duration_str = f"{total_hours} hour{'s' if total_hours != 1 else ''}"
            with get_db() as conn:
                active = conn.execute(
                    "SELECT expires_at FROM lvl_active_big_booster WHERE user_id=? AND guild_id=? AND expires_at > ?",
                    (self.member.id, self.guild.id, now)
                ).fetchone()
            if active:
                remaining = active[0] - now
                remaining_hours = remaining.total_seconds() / 3600
                self.active_duration = remaining_hours
                self.confirm_btn.label = "Extend"
                self.confirm_btn.style = discord.ButtonStyle.primary
                extra_text = f"\n\n⚠️ You already have an active **{self.bname}** with **{remaining_hours:.1f} hours** left.\nUsing this will **extend** it by {duration_str}."
            else:
                self.active_duration = None
                self.confirm_btn.label = "Use"
                self.confirm_btn.style = discord.ButtonStyle.success
                extra_text = ""
        else:
            gain = "Unknown"
            duration_str = "unknown"
            extra_text = ""

        embed = discord.Embed(
            title=f"{self.emoji} **Confirm Use**",
            description=(
                f"**Item:** {self.bname}\n"
                f"**Available:** {self.available}\n\n"
                f"**You will gain**\n"
                f"**{gain}** for **{duration_str}**{extra_text}"
            ),
            color=discord.Color.blurple()
        )
        thumb_url = emoji_to_url(str(self.emoji))
        if thumb_url:
            embed.set_thumbnail(url=thumb_url)

        await interaction.response.edit_message(embed=embed, view=self)

    async def confirm_callback(self, interaction: discord.Interaction):
        await self._apply_booster(interaction, quantity=1)

    async def cancel_callback(self, interaction: discord.Interaction):
        # Return to progress with a fresh LvlView
        fresh_lvl_view = LvlView(self.member, self.guild, "progress")
        udata = get_lvl_user(self.member.id, self.guild.id)
        embed = build_progress_embed(self.member, udata, self.guild.id)
        await interaction.response.edit_message(embed=embed, view=fresh_lvl_view)

    async def _apply_booster(self, interaction: discord.Interaction, quantity: int):
        if quantity > self.available:
            await interaction.response.send_message("Not enough boosters.", ephemeral=True)
            return

        now = datetime.now(timezone.utc)
        PCT_MAP = {"pct_10": 10, "pct_25": 25, "pct_50": 50, "pct_75": 75, "pct_100": 100}
        BIG_MAP = {
            "dbl_1h": (2, 1), "dbl_12h": (2, 12), "dbl_24h": (2, 24),
            "tri_1h": (3, 1), "tri_12h": (3, 12), "tri_24h": (3, 24),
            "5x_24h": (5, 24), "5x_3d": (5, 72),
        }

        if self.btype in PCT_MAP:
            pct = PCT_MAP[self.btype]
            base_hours = 1
            total_hours = quantity * base_hours
            duration_str = f"{total_hours} hour{'s' if total_hours != 1 else ''}"
            with get_db() as conn:
                conn.execute(
                    "UPDATE lvl_booster_inv SET quantity = quantity - ? WHERE user_id=? AND guild_id=? AND booster_type=?",
                    (quantity, self.member.id, self.guild.id, self.btype)
                )
                existing = conn.execute(
                    "SELECT expires_at FROM lvl_boosters WHERE user_id=? AND guild_id=? AND booster_type=? AND expires_at > ?",
                    (self.member.id, self.guild.id, self.btype, now)
                ).fetchone()
                if existing and self.active_duration is not None:
                    new_expiry = existing[0] + timedelta(hours=total_hours)
                    conn.execute(
                        "UPDATE lvl_boosters SET expires_at = ? WHERE user_id=? AND guild_id=? AND booster_type=? AND expires_at > ?",
                        (new_expiry, self.member.id, self.guild.id, self.btype, now)
                    )
                else:
                    expires = now + timedelta(hours=total_hours)
                    conn.execute(
                        "INSERT INTO lvl_boosters (user_id, guild_id, booster_type, pct, expires_at) VALUES (?,?,?,?,?)",
                        (self.member.id, self.guild.id, self.btype, pct, expires)
                    )
                conn.commit()
            remaining = self.available - quantity
        elif self.btype in BIG_MAP:
            mult, base_hours = BIG_MAP[self.btype]
            total_hours = quantity * base_hours
            if total_hours >= 24:
                days = total_hours // 24
                remainder = total_hours % 24
                if remainder == 0:
                    duration_str = f"{days} day{'s' if days != 1 else ''}"
                else:
                    duration_str = f"{days} day{'s' if days != 1 else ''} and {remainder} hours"
            else:
                duration_str = f"{total_hours} hour{'s' if total_hours != 1 else ''}"
            with get_db() as conn:
                conn.execute(
                    "UPDATE lvl_big_boosters SET quantity = quantity - ? WHERE user_id=? AND guild_id=? AND booster_type=?",
                    (quantity, self.member.id, self.guild.id, self.btype)
                )
                existing = conn.execute(
                    "SELECT expires_at FROM lvl_active_big_booster WHERE user_id=? AND guild_id=?",
                    (self.member.id, self.guild.id)
                ).fetchone()
                if existing and existing[0] > now:
                    new_expiry = existing[0] + timedelta(hours=total_hours)
                else:
                    new_expiry = now + timedelta(hours=total_hours)
                conn.execute(
                    "INSERT OR REPLACE INTO lvl_active_big_booster (user_id, guild_id, booster_type, multiplier, expires_at) VALUES (?,?,?,?,?)",
                    (self.member.id, self.guild.id, self.btype, mult, new_expiry)
                )
                conn.commit()
            remaining = self.available - quantity
        else:
            await interaction.response.send_message("Unknown booster type.", ephemeral=True)
            return

        # Success embed – edit same message with Back button
        success_embed = discord.Embed(
            title=f"{self.emoji} **Booster Activated**",
            description=(
                f"You used **{quantity}x {self.bname}**\n"
                f"Remaining: **{remaining}**\n"
                f"Total duration: **{duration_str}**"
            ),
            color=discord.Color.green()
        )
        thumb_url = emoji_to_url(str(self.emoji))
        if thumb_url:
            success_embed.set_thumbnail(url=thumb_url)

        # Create a fresh LvlView for the Back button
        class SuccessBackView(discord.ui.View):
            def __init__(self, member, guild):
                super().__init__(timeout=60)
                self.member = member
                self.guild = guild
            @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
            async def back_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                fresh_lvl = LvlView(self.member, self.guild, "progress")
                udata = get_lvl_user(self.member.id, self.guild.id)
                prog_embed = build_progress_embed(self.member, udata, self.guild.id)
                await btn_interaction.response.edit_message(embed=prog_embed, view=fresh_lvl)

        back_view = SuccessBackView(self.member, self.guild)
        await interaction.response.edit_message(embed=success_embed, view=back_view)


class BoosterQuantityView(DisableOnTimeoutView):
    def __init__(self, member, guild, btype, bname, emoji, available, lvl_view):
        super().__init__(timeout=60)
        self.member = member
        self.guild = guild
        self.btype = btype
        self.bname = bname
        self.emoji = emoji
        self.available = available
        self.original_lvl_view = lvl_view
        self.quantity = 1
        self.active_duration = None

        # Number buttons 1–10
        self.number_buttons = []
        for i in range(1, 11):
            btn = discord.ui.Button(label=str(i), style=discord.ButtonStyle.secondary, row=(i-1)//5)
            btn.callback = self.make_quantity_callback(i)
            self.add_item(btn)
            self.number_buttons.append(btn)
        self.update_number_button_styles()

        max_btn = discord.ui.Button(label="Max", style=discord.ButtonStyle.primary, row=2)
        max_btn.callback = self.max_callback
        self.add_item(max_btn)

        custom_btn = discord.ui.Button(label="Custom", style=discord.ButtonStyle.primary, row=2)
        custom_btn.callback = self.custom_callback
        self.add_item(custom_btn)

        self.use_btn = discord.ui.Button(label="Use", style=discord.ButtonStyle.success, row=3)
        self.use_btn.callback = self.use_callback
        self.add_item(self.use_btn)

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary, row=3)
        back_btn.callback = self.back_callback
        self.add_item(back_btn)

    def update_number_button_styles(self):
        for i, btn in enumerate(self.number_buttons, start=1):
            if i == self.quantity:
                btn.style = discord.ButtonStyle.success
            else:
                btn.style = discord.ButtonStyle.secondary

    def make_quantity_callback(self, qty):
        async def callback(interaction: discord.Interaction):
            self.quantity = qty
            self.update_number_button_styles()
            await self.update_display(interaction, keep_view=True)
        return callback

    async def max_callback(self, interaction: discord.Interaction):
        self.quantity = self.available
        self.update_number_button_styles()
        await self.update_display(interaction, keep_view=True)

    async def custom_callback(self, interaction: discord.Interaction):
        modal = discord.ui.Modal(title="Custom Quantity")
        inp = discord.ui.TextInput(label=f"Quantity (1-{self.available})", placeholder="Enter a number")
        modal.add_item(inp)
        async def on_submit(modal_interaction):
            try:
                qty = int(inp.value)
                if qty < 1 or qty > self.available:
                    raise ValueError
                self.quantity = qty
                self.update_number_button_styles()
                await self.update_display(modal_interaction, keep_view=True)
            except ValueError:
                await modal_interaction.response.send_message(f"Enter a number between 1 and {self.available}.", ephemeral=True)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    async def update_display(self, interaction: discord.Interaction, keep_view=False):
        PCT_MAP = {"pct_10": 10, "pct_25": 25, "pct_50": 50, "pct_75": 75, "pct_100": 100}
        BIG_MAP = {
            "dbl_1h": (2, 1), "dbl_12h": (2, 12), "dbl_24h": (2, 24),
            "tri_1h": (3, 1), "tri_12h": (3, 12), "tri_24h": (3, 24),
            "5x_24h": (5, 24), "5x_3d": (5, 72),
        }
        now = datetime.now(timezone.utc)

        if self.btype in PCT_MAP:
            pct = PCT_MAP[self.btype]
            gain = f"+{pct}% XP"
            base_hours = 1
            total_hours = self.quantity * base_hours
            duration_str = f"{total_hours} hour{'s' if total_hours != 1 else ''}"
            with get_db() as conn:
                active = conn.execute(
                    "SELECT expires_at FROM lvl_boosters WHERE user_id=? AND guild_id=? AND booster_type=? AND expires_at > ?",
                    (self.member.id, self.guild.id, self.btype, now)
                ).fetchone()
            if active:
                remaining = active[0] - now
                remaining_hours = remaining.total_seconds() / 3600
                self.active_duration = remaining_hours
                self.use_btn.label = "Extend"
                self.use_btn.style = discord.ButtonStyle.primary
                extra_text = f"\n\n⚠️ You already have an active **{self.bname}** with **{remaining_hours:.1f} hours** left.\nUsing this will **extend** it by {duration_str}."
            else:
                self.active_duration = None
                self.use_btn.label = "Use"
                self.use_btn.style = discord.ButtonStyle.success
                extra_text = ""
        elif self.btype in BIG_MAP:
            mult, base_hours = BIG_MAP[self.btype]
            gain = f"{mult}x XP"
            total_hours = self.quantity * base_hours
            if total_hours >= 24:
                days = total_hours // 24
                remainder = total_hours % 24
                if remainder == 0:
                    duration_str = f"{days} day{'s' if days != 1 else ''}"
                else:
                    duration_str = f"{days} day{'s' if days != 1 else ''} and {remainder} hours"
            else:
                duration_str = f"{total_hours} hour{'s' if total_hours != 1 else ''}"
            with get_db() as conn:
                active = conn.execute(
                    "SELECT expires_at FROM lvl_active_big_booster WHERE user_id=? AND guild_id=? AND expires_at > ?",
                    (self.member.id, self.guild.id, now)
                ).fetchone()
            if active:
                remaining = active[0] - now
                remaining_hours = remaining.total_seconds() / 3600
                self.active_duration = remaining_hours
                self.use_btn.label = "Extend"
                self.use_btn.style = discord.ButtonStyle.primary
                extra_text = f"\n\n⚠️ You already have an active **{self.bname}** with **{remaining_hours:.1f} hours** left.\nUsing this will **extend** it by {duration_str}."
            else:
                self.active_duration = None
                self.use_btn.label = "Use"
                self.use_btn.style = discord.ButtonStyle.success
                extra_text = ""
        else:
            gain = "Unknown"
            duration_str = "unknown"
            extra_text = ""

        embed = discord.Embed(
            title=f"{self.emoji} **Confirm Use**",
            description=(
                f"**Item:** {self.bname}\n"
                f"**Available:** {self.available}\n\n"
                f"**You are using**\n"
                f"- Quantity: **{self.quantity}**\n\n"
                f"**You will gain**\n"
                f"**{gain}** for **{duration_str}** (total){extra_text}"
            ),
            color=discord.Color.blurple()
        )
        thumb_url = emoji_to_url(str(self.emoji))
        if thumb_url:
            embed.set_thumbnail(url=thumb_url)

        await interaction.response.edit_message(embed=embed, view=self)

    async def use_callback(self, interaction: discord.Interaction):
        if self.quantity > self.available:
            await interaction.response.send_message("Not enough boosters.", ephemeral=True)
            return

        now = datetime.now(timezone.utc)
        PCT_MAP = {"pct_10": 10, "pct_25": 25, "pct_50": 50, "pct_75": 75, "pct_100": 100}
        BIG_MAP = {
            "dbl_1h": (2, 1), "dbl_12h": (2, 12), "dbl_24h": (2, 24),
            "tri_1h": (3, 1), "tri_12h": (3, 12), "tri_24h": (3, 24),
            "5x_24h": (5, 24), "5x_3d": (5, 72),
        }

        if self.btype in PCT_MAP:
            pct = PCT_MAP[self.btype]
            base_hours = 1
            total_hours = self.quantity * base_hours
            duration_str = f"{total_hours} hour{'s' if total_hours != 1 else ''}"
            with get_db() as conn:
                conn.execute(
                    "UPDATE lvl_booster_inv SET quantity = quantity - ? WHERE user_id=? AND guild_id=? AND booster_type=?",
                    (self.quantity, self.member.id, self.guild.id, self.btype)
                )
                existing = conn.execute(
                    "SELECT expires_at FROM lvl_boosters WHERE user_id=? AND guild_id=? AND booster_type=? AND expires_at > ?",
                    (self.member.id, self.guild.id, self.btype, now)
                ).fetchone()
                if existing and self.active_duration is not None:
                    new_expiry = existing[0] + timedelta(hours=total_hours)
                    conn.execute(
                        "UPDATE lvl_boosters SET expires_at = ? WHERE user_id=? AND guild_id=? AND booster_type=? AND expires_at > ?",
                        (new_expiry, self.member.id, self.guild.id, self.btype, now)
                    )
                else:
                    expires = now + timedelta(hours=total_hours)
                    conn.execute(
                        "INSERT INTO lvl_boosters (user_id, guild_id, booster_type, pct, expires_at) VALUES (?,?,?,?,?)",
                        (self.member.id, self.guild.id, self.btype, pct, expires)
                    )
                conn.commit()
            remaining = self.available - self.quantity
        elif self.btype in BIG_MAP:
            mult, base_hours = BIG_MAP[self.btype]
            total_hours = self.quantity * base_hours
            if total_hours >= 24:
                days = total_hours // 24
                remainder = total_hours % 24
                if remainder == 0:
                    duration_str = f"{days} day{'s' if days != 1 else ''}"
                else:
                    duration_str = f"{days} day{'s' if days != 1 else ''} and {remainder} hours"
            else:
                duration_str = f"{total_hours} hour{'s' if total_hours != 1 else ''}"
            with get_db() as conn:
                conn.execute(
                    "UPDATE lvl_big_boosters SET quantity = quantity - ? WHERE user_id=? AND guild_id=? AND booster_type=?",
                    (self.quantity, self.member.id, self.guild.id, self.btype)
                )
                existing = conn.execute(
                    "SELECT expires_at FROM lvl_active_big_booster WHERE user_id=? AND guild_id=?",
                    (self.member.id, self.guild.id)
                ).fetchone()
                if existing and existing[0] > now:
                    new_expiry = existing[0] + timedelta(hours=total_hours)
                else:
                    new_expiry = now + timedelta(hours=total_hours)
                conn.execute(
                    "INSERT OR REPLACE INTO lvl_active_big_booster (user_id, guild_id, booster_type, multiplier, expires_at) VALUES (?,?,?,?,?)",
                    (self.member.id, self.guild.id, self.btype, mult, new_expiry)
                )
                conn.commit()
            remaining = self.available - self.quantity
        else:
            await interaction.response.send_message("Unknown booster type.", ephemeral=True)
            return

        # Success embed – edit same message with Back button
        success_embed = discord.Embed(
            title=f"{self.emoji} **Booster Activated**",
            description=(
                f"You used **{self.quantity}x {self.bname}**\n"
                f"Remaining: **{remaining}**\n"
                f"Total duration: **{duration_str}**"
            ),
            color=discord.Color.green()
        )
        thumb_url = emoji_to_url(str(self.emoji))
        if thumb_url:
            success_embed.set_thumbnail(url=thumb_url)

        class SuccessBackView(discord.ui.View):
            def __init__(self, member, guild):
                super().__init__(timeout=60)
                self.member = member
                self.guild = guild
            @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
            async def back_btn(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                fresh_lvl = LvlView(self.member, self.guild, "progress")
                udata = get_lvl_user(self.member.id, self.guild.id)
                prog_embed = build_progress_embed(self.member, udata, self.guild.id)
                await btn_interaction.response.edit_message(embed=prog_embed, view=fresh_lvl)

        back_view = SuccessBackView(self.member, self.guild)
        await interaction.response.edit_message(embed=success_embed, view=back_view)

    async def back_callback(self, interaction: discord.Interaction):
        with get_db() as conn:
            inv = conn.execute(
                "SELECT booster_type, quantity FROM lvl_booster_inv WHERE user_id=? AND guild_id=? AND quantity > 0",
                (self.member.id, self.guild.id)
            ).fetchall()
            big_inv = conn.execute(
                "SELECT booster_type, quantity FROM lvl_big_boosters WHERE user_id=? AND guild_id=? AND quantity > 0",
                (self.member.id, self.guild.id)
            ).fetchall()
        BOOSTER_LABELS = {
            "pct_10": "10% XP Boost", "pct_25": "25% XP Boost",
            "pct_50": "50% XP Boost", "pct_75": "75% XP Boost",
            "pct_100": "100% XP Boost",
            "dbl_1h": "Double XP", "dbl_12h": "Double XP", "dbl_24h": "Double XP",
            "tri_1h": "Triple XP", "tri_12h": "Triple XP", "tri_24h": "Triple XP",
            "5x_24h": "5x XP", "5x_3d": "5x XP",
        }
        options = []
        for btype, qty in inv + big_inv:
            label = BOOSTER_LABELS.get(btype, btype)
            options.append(discord.SelectOption(label=f"{label} ({qty}x)", value=btype))
        view = BoosterSelectView(self.member, self.guild, options, self.original_lvl_view)
        embed = build_booster_embed(self.member, self.guild.id)
        await interaction.response.edit_message(embed=embed, view=view)

class CreditsShopView(DisableOnTimeoutView):
    SHOP_ITEMS = [
        ("double_xp", "Double XP Booster [1 day]", 250),
        ("vip",       "VIP [30 days]",              1000),
        ("elite",     "Elite [30 days]",            2000),
        ("supreme",   "Supreme [30 days]",          10000),
    ]

    def __init__(self, member, guild, parent_view):
        super().__init__(timeout=60)
        self.member = member
        self.guild = guild
        self.parent_view = parent_view

        options = [discord.SelectOption(label=f"{label} ({cost}c)", value=key)
                   for key, label, cost in self.SHOP_ITEMS]
        select = discord.ui.Select(placeholder="Select item to purchase...", options=options)

        async def select_cb(interaction: discord.Interaction):
            chosen = select.values[0]
            item = next((i for i in self.SHOP_ITEMS if i[0] == chosen), None)
            if not item:
                return
            key, label, cost = item
            _shop_emoji_map = {"double_xp": EMOJI_LVL_DOUBLE, "vip": EMOJI_LVL_VIP, "elite": EMOJI_LVL_ELITE, "supreme": EMOJI_LVL_SUPREME}
            _item_emoji = _shop_emoji_map.get(key, "")
            embed = discord.Embed(
                description=f"Do you want to buy {_item_emoji} **{label}** for **{cost}** {EMOJI_LVL_CREDITS} Credits?",
                color=discord.Color.blurple()
            )
            # Pass self (CreditsShopView) so back returns here with select still visible
            confirm_view = ShopConfirmView(self.member, self.guild, key, label, cost, self)
            await interaction.response.edit_message(embed=embed, view=confirm_view)

        select.callback = select_cb
        self.add_item(select)

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
        async def back_cb(interaction: discord.Interaction):
            # Back from credits shop → return to progress with nav buttons
            ensure_lvl_user(self.member.id, self.guild.id)
            udata = get_lvl_user(self.member.id, self.guild.id)
            embed = build_progress_embed(self.member, udata, self.guild.id)
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        back_btn.callback = back_cb
        self.add_item(back_btn)


class ShopConfirmView(DisableOnTimeoutView):
    def __init__(self, member, guild, key, label, cost, parent_view):
        super().__init__(timeout=30)
        self.member = member
        self.guild = guild
        self.key = key
        self.label = label
        self.cost = cost
        self.parent_view = parent_view

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        udata = get_lvl_user(self.member.id, self.guild.id)
        if udata["credits"] < self.cost:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJI_ERROR} **Not enough credits.** You have {udata['credits']:,}.", color=discord.Color.red()),
                ephemeral=True
            )
            return
        now = datetime.now(timezone.utc)
        with get_db() as conn:
            conn.execute("UPDATE lvl_users SET credits = credits - ? WHERE user_id=? AND guild_id=?",
                         (self.cost, self.member.id, self.guild.id))
            if self.key == "double_xp":
                conn.execute(
                    "INSERT OR IGNORE INTO lvl_big_boosters (user_id, guild_id, booster_type, quantity) VALUES (?,?,?,0)",
                    (self.member.id, self.guild.id, "dbl_24h")
                )
                conn.execute(
                    "UPDATE lvl_big_boosters SET quantity = quantity + 1 WHERE user_id=? AND guild_id=? AND booster_type=?",
                    (self.member.id, self.guild.id, "dbl_24h")
                )
            else:
                # VIP/Elite/Supreme
                tier = self.key
                expires = now + timedelta(days=30)
                existing = conn.execute(
                    "SELECT expires_at FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND tier=?",
                    (self.member.id, self.guild.id, tier)
                ).fetchone()
                if existing and existing[0] > now:
                    expires = existing[0] + timedelta(days=30)
                conn.execute(
                    "INSERT OR REPLACE INTO lvl_vip_roles (user_id, guild_id, tier, expires_at) VALUES (?,?,?,?)",
                    (self.member.id, self.guild.id, tier, expires)
                )
                # Grant Discord role
                dr = conn.execute("SELECT role_id FROM lvl_discord_roles WHERE guild_id=? AND tier=?",
                                  (self.guild.id, tier)).fetchone()
                role = self.guild.get_role(dr[0]) if dr else None
                if not role:
                    colors = {"vip": 0x57F287, "elite": 0x5865F2, "supreme": 0xFFD700}
                    icons = {"vip": EMOJI_LVL_VIP, "elite": EMOJI_LVL_ELITE, "supreme": EMOJI_LVL_SUPREME}
                    try:
                        role = await self.guild.create_role(name=tier.capitalize(), color=discord.Color(colors[tier]))
                        if self.guild.premium_tier >= 2:
                            icon_url = emoji_to_url(icons[tier])
                            if icon_url:
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(icon_url) as resp:
                                        if resp.status == 200:
                                            raw = await resp.read()
                                            img = _process_icon_bytes(raw)
                                            await role.edit(icon=img)
                        conn.execute("INSERT OR REPLACE INTO lvl_discord_roles (guild_id, tier, role_id) VALUES (?,?,?)",
                                     (self.guild.id, tier, role.id))
                    except Exception:
                        pass
                # Apply tier-specific Discord permissions to the role
                TIER_PERMS = {
                    "vip": discord.Permissions(
                        stream=True,
                        use_soundboard=True,
                        send_voice_messages=True,
                    ),
                    "elite": discord.Permissions(
                        stream=True,
                        use_soundboard=True,
                        send_voice_messages=True,
                        attach_files=True,
                        create_private_threads=True,
                        add_reactions=True,
                    ),
                    "supreme": discord.Permissions(
                        stream=True,
                        use_soundboard=True,
                        send_voice_messages=True,
                        attach_files=True,
                        create_private_threads=True,
                        add_reactions=True,
                    ),
                }
                if role:
                    try:
                        await role.edit(permissions=TIER_PERMS.get(tier, discord.Permissions()))
                    except Exception:
                        pass
                if role and role not in self.member.roles:
                    try:
                        await self.member.add_roles(role)
                    except Exception:
                        pass
            conn.commit()
        # For supreme, trigger custom role creation if they don't have one yet
        if self.key == "supreme":
            try:
                await create_custom_role_for_user(self.member, self.guild, self.member)
            except Exception:
                pass
        emoji_map = {"double_xp": EMOJI_LVL_DOUBLE, "vip": EMOJI_LVL_VIP, "elite": EMOJI_LVL_ELITE, "supreme": EMOJI_LVL_SUPREME}
        embed = discord.Embed(
            description=f"{EMOJI_LVL_INFO} You bought a {emoji_map.get(self.key, '')} **{self.label}**!",
            color=discord.Color.green()
        )
        # Return to fresh CreditsShopView so select is visible
        lvl_view = self.parent_view.parent_view  # LvlView
        shop_view = CreditsShopView(self.member, self.guild, lvl_view)
        await interaction.response.edit_message(embed=embed, view=shop_view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_credits_embed(self.member, self.guild.id)
        # parent_view is CreditsShopView — rebuild it fresh so select reappears
        shop_view = CreditsShopView(self.member, self.guild, self.parent_view.parent_view)
        await interaction.response.edit_message(embed=embed, view=shop_view)


# ---------- Setup: Level Up Button + Sub-Views ----------
class LevelUpSetupView(DisableOnTimeoutView):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild
        cfg = get_lvl_config(guild.id)
        self._enabled = bool(cfg["enabled"])
        # Set toggle button label/style immediately from current DB state
        for child in self.children:
            if getattr(child, "custom_id", None) == "lvl_toggle":
                child.label = "Disable" if self._enabled else "Enable"
                child.style = discord.ButtonStyle.danger if self._enabled else discord.ButtonStyle.success

    def build_embed(self) -> discord.Embed:
        cfg = get_lvl_config(self.guild.id)
        enabled = bool(cfg["enabled"])
        xp_chs = cfg["xp_channel_ids"]
        lv_chs = cfg["lvlup_channel_ids"]

        def ch_names(ids_str):
            if not ids_str:
                return "All channels"
            parts = []
            for cid in ids_str.split(","):
                cid = cid.strip()
                if cid.isdigit():
                    ch = self.guild.get_channel(int(cid))
                    parts.append(ch.mention if ch else f"`{cid}`")
            return ", ".join(parts) if parts else "All channels"

        announce_ch = "Not set"
        if lv_chs:
            cid = lv_chs.split(",")[0].strip()
            if cid.isdigit():
                ch = self.guild.get_channel(int(cid))
                announce_ch = ch.mention if ch else f"`{cid}`"
        status = f"{EMOJI_SUCCESS} **Enabled**" if enabled else f"{EMOJI_WARNING} **Disabled**"
        embed = discord.Embed(
            title=f"{EMOJI_LVL_SETTINGS} **Member's Level Up**",
            description=(
                f"{EMOJI_LVL_SETTINGS} Add a leveling system for your server\n\n"
                f"**Status:** {status}\n"
                f"**XP Channels:** {ch_names(xp_chs)}\n"
                f"**Announcement Channel:** {announce_ch}"
            ),
            color=discord.Color.green() if enabled else discord.Color.greyple()
        )
        return embed

    async def refresh(self, interaction: discord.Interaction):
        cfg = get_lvl_config(self.guild.id)
        self._enabled = bool(cfg["enabled"])
        # Update enable/disable button label dynamically
        for child in self.children:
            if hasattr(child, "custom_id") and child.custom_id == "lvl_toggle":
                child.label = "Disable" if self._enabled else "Enable"
                child.style = discord.ButtonStyle.danger if self._enabled else discord.ButtonStyle.success
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Enable", style=discord.ButtonStyle.success, custom_id="lvl_toggle", row=0)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ensure_lvl_config(self.guild.id)
        cfg = get_lvl_config(self.guild.id)
        new_state = 0 if cfg["enabled"] else 1
        with get_db() as conn:
            conn.execute("UPDATE lvl_config SET enabled=? WHERE guild_id=?", (new_state, self.guild.id))
            conn.commit()
        if new_state == 0:
            # Disable: remove all level+VIP Discord roles
            await _disable_leveling_roles(self.guild)
        else:
            # Enable: regenerate any roles that users already earned
            await _regenerate_leveling_roles(self.guild)
        await self.refresh(interaction)

    @discord.ui.button(label="Command", style=discord.ButtonStyle.primary, row=1)
    async def cmd_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LvlChannelSelectView(self.guild, "xp_channel_ids", "Command Channels", self)
        embed = discord.Embed(
            title="📢 **Select XP/Command Channels**",
            description="Members can only run `!lvl` and earn chat XP in selected channels.\nSelect multiple or leave empty for all channels.",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Announcement", style=discord.ButtonStyle.primary, row=1)
    async def announce_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LvlAnnounceChannelView(self.guild, self)
        cfg = get_lvl_config(self.guild.id)
        ids = cfg["lvlup_channel_ids"]
        cur_ch = "Not set"
        if ids:
            cid = ids.split(",")[0].strip()
            if cid.isdigit():
                ch = self.guild.get_channel(int(cid))
                cur_ch = ch.mention if ch else f"`{cid}`"
        embed = discord.Embed(
            title="📣 **Level-Up Announcement Channel**",
            description=(
                f"Current channel: {cur_ch}\n\n"
                "Select a single text channel where level-up messages will be sent.\n"
                "Level-up embeds never delete — they stay permanently."
            ),
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Vote", style=discord.ButtonStyle.success, row=1)
    async def vote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = VoteConfigView(self.guild, self)
        cfg = get_lvl_config(self.guild.id)
        embed = discord.Embed(
            title="🗳️ **Vote Configuration**",
            description=(
                f"**Vote Link:** {cfg['vote_link'] or '*(not set)*'}\n"
                f"**Credit Reward:** {cfg['vote_reward_credits']}\n"
                f"**Vote Time:** {cfg['vote_time'] or '*(24h default)*'}"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_setup_embed(interaction, edit=True)


class LvlChannelSelectView(DisableOnTimeoutView):
    def __init__(self, guild, config_key, title, parent_view):
        super().__init__(timeout=60)
        self.guild = guild
        self.config_key = config_key
        self.parent_view = parent_view

        channels = [c for c in guild.text_channels][:25]
        options = [discord.SelectOption(label=f"#{c.name}", value=str(c.id)) for c in channels]
        if not options:
            options = [discord.SelectOption(label="No channels found", value="0")]

        select = discord.ui.ChannelSelect(
            placeholder=f"Select {title} (multi)...",
            min_values=0,
            max_values=min(25, len(guild.text_channels)) if guild.text_channels else 1,
            channel_types=[discord.ChannelType.text]
        )

        async def select_cb(interaction: discord.Interaction):
            ids = ",".join(str(c.id) for c in select.values)
            with get_db() as conn:
                conn.execute(f"UPDATE lvl_config SET {self.config_key}=? WHERE guild_id=?", (ids, self.guild.id))
                conn.commit()
            await interaction.response.edit_message(
                embed=discord.Embed(description=f"{EMOJI_SUCCESS} **Channels saved.**", color=discord.Color.green()),
                view=self
            )

        select.callback = select_cb
        self.add_item(select)

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
        back_btn.callback = back_cb
        self.add_item(back_btn)



class LvlAnnounceChannelView(DisableOnTimeoutView):
    def __init__(self, guild, parent_view):
        super().__init__(timeout=60)
        self.guild = guild
        self.parent_view = parent_view

        select = discord.ui.ChannelSelect(
            placeholder="Select announcement channel...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )

        async def select_cb(interaction: discord.Interaction):
            ch = select.values[0]
            with get_db() as conn:
                conn.execute(
                    "UPDATE lvl_config SET lvlup_channel_ids=? WHERE guild_id=?",
                    (str(ch.id), self.guild.id)
                )
                conn.commit()
            embed = discord.Embed(
                title="📣 **Level-Up Announcement Channel**",
                description=f"{EMOJI_SUCCESS} **Announcement channel set to {ch.mention}.**",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=self)

        select.callback = select_cb
        self.add_item(select)

        clear_btn = discord.ui.Button(label="Clear", style=discord.ButtonStyle.danger)
        async def clear_cb(interaction: discord.Interaction):
            with get_db() as conn:
                conn.execute("UPDATE lvl_config SET lvlup_channel_ids='' WHERE guild_id=?", (self.guild.id,))
                conn.commit()
            embed = discord.Embed(
                title="📣 **Level-Up Announcement Channel**",
                description=f"{EMOJI_SUCCESS} **Announcement channel cleared.** Level-ups will use the system channel.",
                color=discord.Color.orange()
            )
            await interaction.response.edit_message(embed=embed, view=self)
        clear_btn.callback = clear_cb
        self.add_item(clear_btn)

        back_btn = discord.ui.Button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
        back_btn.callback = back_cb
        self.add_item(back_btn)


class VoteConfigView(DisableOnTimeoutView):
    def __init__(self, guild, parent_view):
        super().__init__(timeout=120)
        self.guild = guild
        self.parent_view = parent_view

    @discord.ui.button(label="Set Vote Link", style=discord.ButtonStyle.primary)
    async def set_link(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="Vote Link")
        inp = discord.ui.TextInput(label="Discardia Vote URL", placeholder="https://discardia.gg/...")
        modal.add_item(inp)
        async def on_submit(mi):
            ensure_lvl_config(self.guild.id)
            with get_db() as conn:
                conn.execute("UPDATE lvl_config SET vote_link=? WHERE guild_id=?", (inp.value, self.guild.id))
                conn.commit()
            await mi.response.send_message(embed=discord.Embed(description=f"{EMOJI_SUCCESS} **Vote link saved.**", color=discord.Color.green()), ephemeral=True, delete_after=5)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Credit Reward", style=discord.ButtonStyle.success)
    async def set_credits(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="Vote Credit Reward")
        inp = discord.ui.TextInput(label="Credits per vote", placeholder="e.g. 500")
        modal.add_item(inp)
        async def on_submit(mi):
            try:
                amt = int(inp.value)
            except ValueError:
                await mi.response.send_message("Must be a number.", ephemeral=True)
                return
            ensure_lvl_config(self.guild.id)
            with get_db() as conn:
                conn.execute("UPDATE lvl_config SET vote_reward_credits=? WHERE guild_id=?", (amt, self.guild.id))
                conn.commit()
            await mi.response.send_message(embed=discord.Embed(description=f"{EMOJI_SUCCESS} **Reward set to {amt} credits.**", color=discord.Color.green()), ephemeral=True, delete_after=5)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    @discord.ui.button(emoji=BTN_BACK, label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)


async def _disable_leveling_roles(guild: discord.Guild):
    """Delete all level/VIP/tier Discord roles, keep DB data.
    Also removes the Donor-Join hub channel and all VC data."""
    with get_db() as conn:
        level_roles = conn.execute("SELECT role_id FROM lvl_level_roles WHERE guild_id=?", (guild.id,)).fetchall()
        prestige_roles = conn.execute("SELECT role_id FROM lvl_prestige_roles WHERE guild_id=?", (guild.id,)).fetchall()
        disc_roles = conn.execute("SELECT role_id FROM lvl_discord_roles WHERE guild_id=?", (guild.id,)).fetchall()
    for (rid,) in level_roles + prestige_roles + disc_roles:
        role = guild.get_role(rid)
        if role:
            try:
                await role.delete(reason="Level system disabled")
                await asyncio.sleep(0.3)
            except Exception:
                pass
    with get_db() as conn:
        conn.execute("DELETE FROM lvl_level_roles WHERE guild_id=?", (guild.id,))
        conn.execute("DELETE FROM lvl_prestige_roles WHERE guild_id=?", (guild.id,))
        conn.execute("DELETE FROM lvl_discord_roles WHERE guild_id=?", (guild.id,))
        conn.commit()
    # Remove the Donor-Join hub channel and all VC tables
    with get_db() as conn:
        hub_row = conn.execute("SELECT hub_channel_id FROM vc_hub WHERE guild_id=?", (guild.id,)).fetchone()
    if hub_row:
        hub_ch = guild.get_channel(hub_row[0])
        if hub_ch:
            try:
                await hub_ch.delete(reason="Level system disabled")
            except Exception:
                pass
    with get_db() as conn:
        vc_member_ids = [
            r[0] for r in conn.execute(
                "SELECT channel_id FROM vc_channels WHERE guild_id=?", (guild.id,)
            ).fetchall()
        ]
    for cid in vc_member_ids:
        ch = guild.get_channel(cid)
        if ch:
            try:
                await ch.delete(reason="Level system disabled")
                await asyncio.sleep(0.2)
            except Exception:
                pass
    with get_db() as conn:
        conn.execute("DELETE FROM vc_hub WHERE guild_id=?", (guild.id,))
        conn.execute("DELETE FROM vc_channels WHERE guild_id=?", (guild.id,))
        conn.execute("DELETE FROM vc_settings WHERE guild_id=?", (guild.id,))
        conn.execute("DELETE FROM vc_admin_perms WHERE guild_id=?", (guild.id,))
        conn.execute("DELETE FROM vc_permissions WHERE guild_id=?", (guild.id,))
        conn.execute("DELETE FROM vc_deafened WHERE guild_id=?", (guild.id,))
        conn.execute(
            "DELETE FROM vc_muted WHERE channel_id IN "
            "(SELECT channel_id FROM vc_channels WHERE guild_id=?)", (guild.id,)
        )
        conn.commit()


async def _regenerate_leveling_roles(guild: discord.Guild):
    """Re-create and re-assign all earned level/prestige roles."""
    with get_db() as conn:
        users = conn.execute("SELECT user_id, level, prestige FROM lvl_users WHERE guild_id=?", (guild.id,)).fetchall()
    for (uid, level, prestige) in users:
        member = guild.get_member(uid)
        if not member:
            continue
        for mlvl in MILESTONE_LEVELS:
            if level >= mlvl:
                await grant_level_role(guild, member, mlvl)
                await asyncio.sleep(0.2)
        if prestige > 0:
            for p in range(1, prestige + 1):
                await grant_prestige_role(guild, member, p)
                await asyncio.sleep(0.2)


# ---------- Commands ----------
async def _lvl_channel_check(ctx, cfg) -> bool:
    """Returns True if channel is allowed or no restriction set."""
    if cfg["xp_channel_ids"]:
        allowed = [int(x) for x in cfg["xp_channel_ids"].split(",") if x.strip().isdigit()]
        if allowed and ctx.channel.id not in allowed:
            embed = discord.Embed(
                description=f"{EMOJI_ERROR} **You can only run this command in designated channels.**",
                color=discord.Color.red()
            )
            await send_then_delete(ctx, embed, delay=5)
            return False
    return True

async def _resolve_member(ctx, user_arg: str):
    """Resolve a member from mention, username, or ID string."""
    if not user_arg:
        return ctx.author
    try:
        return await commands.MemberConverter().convert(ctx, user_arg)
    except Exception:
        uid = user_arg.strip().strip("<@!>")
        if uid.isdigit():
            m = ctx.guild.get_member(int(uid))
            if m:
                return m
    return ctx.author


@bot.command(name="lvl")
async def cmd_lvl(ctx: commands.Context, *, user_arg: str = None):
    """Compact level card — !lvl or !lvl @user."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    if not await _lvl_channel_check(ctx, cfg):
        return
    target = await _resolve_member(ctx, user_arg)
    ensure_lvl_user(target.id, ctx.guild.id)
    udata = get_lvl_user(target.id, ctx.guild.id)
    embed = build_compact_lvl_embed(target, udata, ctx.guild.id)
    await ctx.send(embed=embed)


@bot.command(name="stats", aliases=["level", "progress"])
async def cmd_stats(ctx: commands.Context, *, user_arg: str = None):
    """Full milestone progress view with buttons — !stats / !level / !progress."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    if not await _lvl_channel_check(ctx, cfg):
        return
    target = await _resolve_member(ctx, user_arg)
    ensure_lvl_user(target.id, ctx.guild.id)
    udata = get_lvl_user(target.id, ctx.guild.id)
    embed = build_progress_embed(target, udata, ctx.guild.id)
    # Only show interactive view for the command invoker
    if target.id != ctx.author.id:
        await ctx.send(embed=embed)
        return
    view = LvlView(target, ctx.guild, "progress")
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg


@bot.command(name="boosters", aliases=["booster"])
async def cmd_boosters(ctx: commands.Context, *, user_arg: str = None):
    """Open the Booster tab directly — !boosters."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    if not await _lvl_channel_check(ctx, cfg):
        return
    target = await _resolve_member(ctx, user_arg)
    ensure_lvl_user(target.id, ctx.guild.id)
    embed = build_booster_embed(target, ctx.guild.id)
    parent_view = LvlView(target, ctx.guild, "booster")
    # Build inventory options for the select (same as the Booster button)
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        inv = conn.execute(
            "SELECT booster_type, quantity FROM lvl_booster_inv WHERE user_id=? AND guild_id=? AND quantity > 0",
            (target.id, ctx.guild.id)
        ).fetchall()
        big_inv = conn.execute(
            "SELECT booster_type, quantity FROM lvl_big_boosters WHERE user_id=? AND guild_id=? AND quantity > 0",
            (target.id, ctx.guild.id)
        ).fetchall()
    BOOSTER_LABELS = {
        "pct_10": "10% XP Booster [1 hour]",
        "pct_25": "25% XP Booster [1 hour]",
        "pct_50": "50% XP Booster [1 hour]",
        "pct_75": "75% XP Booster [1 hour]",
        "pct_100": "100% XP Booster [1 hour]",
        "double": "Double XP [1 day]",
        "triple": "Triple XP [1 day]",
        "5x": "5x XP [1 day]",
    }
    options = []
    for btype, qty in list(inv) + list(big_inv):
        label = BOOSTER_LABELS.get(btype, btype)
        options.append(discord.SelectOption(label=f"{label} ({qty}x)", value=btype))
    if options and target.id == ctx.author.id:
        view = BoosterSelectView(target, ctx.guild, options, parent_view)
    else:
        view = parent_view
    msg = await ctx.send(embed=embed, view=view)
    parent_view.message = msg
    view.message = msg


@bot.command(name="credits", aliases=["credit"])
async def cmd_credits(ctx: commands.Context, *, user_arg: str = None):
    """Open the Credits tab directly — !credits / !credit."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    if not await _lvl_channel_check(ctx, cfg):
        return
    target = await _resolve_member(ctx, user_arg)
    ensure_lvl_user(target.id, ctx.guild.id)
    embed = build_credits_embed(target, ctx.guild.id)
    parent_view = LvlView(target, ctx.guild, "credits")
    if target.id == ctx.author.id:
        view = CreditsShopView(target, ctx.guild, parent_view)
    else:
        view = parent_view
    msg = await ctx.send(embed=embed, view=view)
    parent_view.message = msg
    view.message = msg


@bot.command(name="leaderboard", aliases=["lb"])
async def cmd_leaderboard(ctx: commands.Context):
    """Open the Leaderboard tab directly — !leaderboard / !lb."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    if not await _lvl_channel_check(ctx, cfg):
        return
    ensure_lvl_user(ctx.author.id, ctx.guild.id)
    embed = build_leaderboard_embed(ctx.guild)
    view = LvlView(ctx.author, ctx.guild, "leaderboard")
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg


@bot.command(name="xp")
async def cmd_xp(ctx: commands.Context, user: discord.Member = None):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    target = user or ctx.author
    ensure_lvl_user(target.id, ctx.guild.id)
    udata = get_lvl_user(target.id, ctx.guild.id)
    # Compute server rank by total_earned
    with get_db() as conn:
        rank_row = conn.execute(
            "SELECT COUNT(*) FROM lvl_users WHERE guild_id=? AND total_earned > ?",
            (ctx.guild.id, udata["total_earned"])
        ).fetchone()
        vc_row = conn.execute(
            "SELECT total_minutes FROM lvl_vc_time WHERE user_id=? AND guild_id=?",
            (target.id, ctx.guild.id)
        ).fetchone()
    rank = (rank_row[0] + 1) if rank_row else 1
    vc_mins = vc_row[0] if vc_row else 0
    vc_hrs = vc_mins // 60
    vc_rem = vc_mins % 60
    prestige = udata.get("prestige", 0)
    level = udata.get("level", 0)
    prestige_str = (
        f" — {PRESTIGE_EMOJIS.get(prestige, '')} Prestige **{prestige}**" if prestige > 0 else ""
    )
    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_author(
        name=f"{target.display_name}'s XP",
        icon_url=target.avatar.url if target.avatar else None
    )
    embed.set_thumbnail(url=target.avatar.url if target.avatar else None)
    embed.description = (
        f"\u200b\n"
        f"**{udata['total_earned']:,} XP** {EMOJI_LVL_USER_XP}\n"
        f"\u200b\n"
        f"{EMOJI_LVL_PROGRESS} **Level {level}**{prestige_str}\n"
        f"{EMOJI_ROLE_RANKS} **Server Rank: #{rank}**\n"
        f"{EMOJI_LVL_TIME} **VC Time: {vc_hrs}h {vc_rem}m**\n"
        f"\u200b"
    )
    await ctx.send(embed=embed)


@bot.command(name="vote")
async def cmd_vote(ctx: commands.Context):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    embed = build_vote_embed(ctx.guild, cfg)
    msg = await ctx.send(embed=embed)


DONOR_GIF = "https://cdn.discordapp.com/attachments/1506581968484175934/1511126098874990734/InShot_20260602_035422555.gif?ex=6a1f5159&is=6a1dffd9&hm=f80b257437edac98ad90258d3c988698be7295a1367ad0240ed2b8c1a8128b88&"


def build_donor_page(page: int) -> discord.Embed:
    if page == 1:
        embed = discord.Embed(
            description=(
                "<a:badge:1511017511817052221> __**Booster Benefits**__\n\n"
                "<a:Boost_Badge:1511194384467624106>\n"
                " <:extend_end:1511143598664712343> Ability to Create Custom VC\n"
                "<a:Boost_Badge:1511194384467624106>\n"
                " <:extend_end:1511143598664712343> Ability to Create Threads\n"
                "<a:Boost_Badge:1511194384467624106>\n"
                " <:extend_end:1511143598664712343> Ability to Boost any custom role **5x** daily\n"
                "<a:Boost_Badge:1511194384467624106>\n"
                " <:extend_end:1511143598664712343> **3x** XP gain 24 hours\n"
                "<a:Boost_Badge:1511194384467624106>\n"
                " <:extend_end:1511143598664712343> Use any server's emojis\n"
                "<a:Boost_Badge:1511194384467624106>\n"
                " <:extend_end:1511143598664712343> A customizable role for as long as booster stays available in the server\n"
                "<a:Boost_Badge:1511194384467624106>\n"
                " <:extend_end:1511143598664712343> First Priority in Support List"
            ),
            color=0xFF73FA
        )
        embed.set_footer(text="Page 1/5 • Boost this server to immediately receive the perks.")
    elif page == 2:
        embed = discord.Embed(
            description=(
                "<:Booster:1511130208869154897> __**Double XP Boosters**__\n"
                "1. **1hr** - Doubles your XP gain for 1 hour\n"
                "2. **12hrs** - Doubles your XP for 12 hours\n"
                "3. **24hrs** - Doubles your XP gain for 24 hours\n\n"
                "<:Booster_Triple:1511130404957065401> __**Triple XP Boosters**__\n"
                "4. **1hr** - Triple your XP gain for 1 hour\n"
                "5. **12hrs** - Triple your XP gain for 12 hours\n"
                "6. **24hrs** - Triple your XP gain for 24 hours\n\n"
                "<:5x:1511192133665689703> __**5x XP Boosters**__\n"
                "7. **24hrs** - Multiplier Increased by 4\n"
                "8. **3d** - 5x Your XP gain for 3 days"
            ),
            color=0xFF73FA
        )
        embed.set_footer(text="Page 2/5 • We currently don't have a store. To get these boosters ping an Admin.")
    elif page == 3:
        embed = discord.Embed(
            description=(
                "<a:pink:1511111646641127545> __**General Perk**__\n"
                "<a:green:1510987722494443671> Earn 150% more XP and coins per minute\n"
                "<a:green:1510987722494443671> Instant streaming/cam access\n"
                "<a:green:1510987722494443671> Ability to send voice notes\n"
                "<a:green:1510987722494443671> Access to VC soundboard\n\n"
                "<a:daily_perk:1510988210023436348> __**Daily Benefits**__\n"
                "<a:green:1510987722494443671> Use `.bless @user` to grant yourself or another member a **2x XP** role for 1 hour (**3** per day)"
            ),
            color=0x57F287
        )
        embed.set_footer(text="Page 3/5 • Type !Credits to view your credits and purchase the role.")
    elif page == 4:
        embed = discord.Embed(
            description=(
                "<a:pink:1511111646641127545> __**General Perks**__\n"
                "<a:blue:1510987510740811826> Earn 200% more XP and coins per minute\n"
                "<a:blue:1510987510740811826> Ability to post pictures\n"
                "<a:blue:1510987510740811826> Instant streaming/cam access\n"
                "<a:blue:1510987510740811826> Ability to send voice messages\n"
                "<a:blue:1510987510740811826> Ability to add reactions to messages\n"
                "<a:blue:1510987510740811826> Ability to create private threads\n"
                "<a:blue:1510987510740811826> Access to VC soundboard\n"
                "<a:blue:1510987510740811826> Full access to custom voice channels\n\n"
                "<a:daily_perk:1510988210023436348> __**Daily Benefits**__\n"
                "<a:blue:1510987510740811826> Use `.bless @user` to grant yourself or another member a **3x XP** role for 1 hour (**6** per day)\n\n"
                "<a:reaction:1510993140138381472> __**Reactions on Ping**__\n"
                "<a:blue:1510987510740811826> Customizable & Toggleable reactions when mentioned\n"
                "<a:blue:1510987510740811826> Use `!reaction set [emoji] [emoji2] [emoji3]` to customize"
            ),
            color=0x5865F2
        )
        embed.set_image(url=DONOR_GIF)
        embed.set_footer(text="Page 4/5 • Type !Credits to view your credits and purchase the role.")
    else:
        embed = discord.Embed(
            description=(
                "<a:pink:1511111646641127545> __**General Perks**__\n"
                "<a:golden:1510987861409796209> Earn 300% more XP and coins per minute\n"
                "<a:golden:1510987861409796209> Ability to post pictures\n"
                "<a:golden:1510987861409796209> Instant streaming/cam access\n"
                "<a:golden:1510987861409796209> Ability to add reactions to messages\n"
                "<a:golden:1510987861409796209> Ability to create private threads\n"
                "<a:golden:1510987861409796209> Access to VC soundboard\n"
                "<a:golden:1510987861409796209> Ability to send discord's voice messages\n"
                "<a:golden:1510987861409796209> Full access to custom voice channels\n\n"
                "<:gift:1511114423186751518> __**Custom Role + Voice Channel**__\n"
                "<a:golden:1510987861409796209> Ability to customize all aspects (Name, Icon, Color) — Use `!Role Info`\n"
                "<a:golden:1510987861409796209> Ability to give and remove users from the role\n"
                "<a:golden:1510987861409796209> Option to Create your own permanent VC\n\n"
                "<a:daily_perk:1510988210023436348> __**Daily Benefits**__\n"
                "<a:golden:1510987861409796209> Use `.bless @user` to grant yourself or another member a **5x XP** role for 1 hour (**10** per day)\n\n"
                "<a:reaction:1510993140138381472> __**Reaction on Ping**__\n"
                "<a:golden:1510987861409796209> Customizable & Toggleable reactions when mentioned\n"
                "<a:golden:1510987861409796209> Use `!reaction set [emoji1] [emoji2] [emoji3]` to customize"
            ),
            color=0xFFD700
        )
        embed.set_image(url=DONOR_GIF)
        embed.set_footer(text="Page 5/5 • Visit !Credits to purchase the role or ask admin.")
    return embed


class DonorView(DisableOnTimeoutView):
    def __init__(self, page: int = 1):
        super().__init__(timeout=120)
        self.page = page
        self._build_components()

    def _build_components(self):
        self.clear_items()
        select = discord.ui.Select(
            placeholder="Jump to a tier...",
            options=[
                discord.SelectOption(
                    label="Server Booster", value="1",
                    emoji=discord.PartialEmoji(name="Badge_2", id=1511203977457438771)
                ),
                discord.SelectOption(
                    label="Booster", value="2",
                    emoji=discord.PartialEmoji(name="Booster", id=1511130208869154897)
                ),
                discord.SelectOption(
                    label="VIP", value="3",
                    emoji=discord.PartialEmoji(name="pink", id=1511111646641127545, animated=True)
                ),
                discord.SelectOption(
                    label="Elite", value="4",
                    emoji=discord.PartialEmoji(name="blue", id=1510987510740811826, animated=True)
                ),
                discord.SelectOption(
                    label="Supreme", value="5",
                    emoji=discord.PartialEmoji(name="golden", id=1510987861409796209, animated=True)
                ),
            ],
            row=0
        )
        async def select_cb(interaction: discord.Interaction):
            self.page = int(interaction.data['values'][0])
            self._build_components()
            await interaction.response.edit_message(embed=build_donor_page(self.page), view=self)
        select.callback = select_cb
        self.add_item(select)
        if self.page > 1:
            prev_btn = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, emoji=BTN_BACK, row=1)
            async def prev_cb(interaction: discord.Interaction):
                self.page -= 1
                self._build_components()
                await interaction.response.edit_message(embed=build_donor_page(self.page), view=self)
            prev_btn.callback = prev_cb
            self.add_item(prev_btn)
        if self.page < 5:
            next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary, emoji="▶️", row=1)
            async def next_cb(interaction: discord.Interaction):
                self.page += 1
                self._build_components()
                await interaction.response.edit_message(embed=build_donor_page(self.page), view=self)
            next_btn.callback = next_cb
            self.add_item(next_btn)


@bot.command(name="donor")
async def cmd_donor(ctx: commands.Context):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled on this server.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return
    view = DonorView(page=1)
    msg = await ctx.send(embed=build_donor_page(1), view=view)
    view.message = msg


# ---------- .bless command ----------
@bot.command(name="bless")
async def cmd_bless(ctx: commands.Context, *, args: str = ""):
    # Only fires on "." prefix — server prefix cannot trigger this
    if not ctx.message.content.startswith("."):
        return

    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return

    # ".bless status" — show blessing status
    if args.strip().lower() == "status":
        now = datetime.now(timezone.utc)
        with get_db() as conn:
            active = conn.execute(
                "SELECT blessing_type, multiplier, expires_at FROM lvl_blessings WHERE user_id=? AND guild_id=? AND expires_at > ?",
                (ctx.author.id, ctx.guild.id, now)
            ).fetchone()
            daily_rows = conn.execute(
                "SELECT bless_type, used, last_reset FROM lvl_bless_daily WHERE user_id=? AND guild_id=?",
                (ctx.author.id, ctx.guild.id)
            ).fetchall()
            tiers = conn.execute(
                "SELECT tier FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND expires_at > ?",
                (ctx.author.id, ctx.guild.id, now)
            ).fetchall()
        tiers = [t[0] for t in tiers]
        
        BLESS_DATA_S = {
            "vip":     {"label": "Small Blessing",  "mult": 2, "daily": 3, "emoji": "<:small_blessing:1512552245101859028>"},
            "elite":   {"label": "Medium Blessing", "mult": 3, "daily": 6, "emoji": "<:medium_blessing:1512552329562292274>"},
            "supreme": {"label": "Large Blessing",  "mult": 5, "daily": 10, "emoji": "<:large_blessing:1512552388618354899>"},
        }
        
        embed = discord.Embed(color=discord.Color.blurple())
        embed.set_author(name="Blessing Status", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        if not active:
            embed.description = f"{EMOJI_LVL_INFO} You do not have an active blessing right now."
        else:
            btype, mult, exp = active
            exp_ts = int(exp.timestamp())
            label = BLESS_DATA_S.get(btype, {}).get("label", btype.capitalize())
            emoji = BLESS_DATA_S.get(btype, {}).get("emoji", EMOJI_LVL_BLESS)
            embed.description = f"{emoji} **{label}** until <t:{exp_ts}:t> (<t:{exp_ts}:R>)"
        
        daily_lines = []
        for btype in ["vip", "elite", "supreme"]:
            if btype not in tiers:
                continue
            bd = BLESS_DATA_S[btype]
            used_row = next((r for r in daily_rows if r[0] == btype), None)
            used = 0
            if used_row:
                last_reset = used_row[2]
                if last_reset and (now - last_reset).total_seconds() < 86400:
                    used = used_row[1]
            remaining = bd["daily"] - used
            daily_lines.append(f"**{bd['label']}:** {remaining}/{bd['daily']} remaining")
        if daily_lines:
            embed.add_field(name="Daily Blessings", value="\n".join(daily_lines), inline=False)
        await ctx.send(embed=embed)
        return

    # Parse args: optional type, then mention/reply
    parts = args.strip().split()
    bless_type = None
    receiver = None

    BLESS_TYPES = {"small": "vip", "medium": "elite", "large": "supreme"}
    BLESS_DATA = {
        "vip":     {"label": "Small Blessing",  "mult": 2,  "daily": 3,  "tier": "vip",    "emoji": "<:small_blessing:1512552245101859028>"},
        "elite":   {"label": "Medium Blessing", "mult": 3,  "daily": 6,  "tier": "elite",  "emoji": "<:medium_blessing:1512552329562292274>"},
        "supreme": {"label": "Large Blessing",  "mult": 5,  "daily": 10, "tier": "supreme", "emoji": "<:large_blessing:1512552388618354899>"},
    }

    now = datetime.now(timezone.utc)

    # Determine bless type from parts
    if parts and parts[0].lower() in BLESS_TYPES:
        bless_type = BLESS_TYPES[parts[0].lower()]
        parts = parts[1:]
    
    # Resolve receiver from mention or reply
    if ctx.message.reference:
        try:
            ref = ctx.message.reference.resolved or await ctx.channel.fetch_message(ctx.message.reference.message_id)
            receiver = ref.author
        except Exception:
            pass
    if not receiver and parts:
        try:
            receiver = await commands.MemberConverter().convert(ctx, parts[0])
        except Exception:
            pass

    if not receiver:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `.bless [small/medium/large] <@user>` or reply to their message.", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=10)
        return

    is_self_bless = (receiver.id == ctx.author.id)

    # Check which VIP tiers the giver has
    with get_db() as conn:
        tiers = conn.execute(
            "SELECT tier FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND expires_at > ?",
            (ctx.author.id, ctx.guild.id, now)
        ).fetchall()
    tiers = [t[0] for t in tiers]

    if not tiers:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You need VIP, Elite, or Supreme to use bless.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return

    # Pick bless type: if no type specified, use largest available
    tier_priority = ["supreme", "elite", "vip"]
    if bless_type is None:
        bless_type = next((t for t in tier_priority if t in tiers), None)
    elif bless_type not in tiers:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You don't have that tier.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return

    bdata = BLESS_DATA[bless_type]

    # Check daily limit
    with get_db() as conn:
        daily = conn.execute(
            "SELECT used, last_reset FROM lvl_bless_daily WHERE user_id=? AND guild_id=? AND bless_type=?",
            (ctx.author.id, ctx.guild.id, bless_type)
        ).fetchone()
    used = 0
    if daily:
        last_reset = daily[1]
        if last_reset and (now - last_reset).total_seconds() < 86400:
            used = daily[0]
        else:
            used = 0

    self_bless_limit = 1
    daily_limit = self_bless_limit if is_self_bless else bdata["daily"]
    if is_self_bless and used >= self_bless_limit:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can only bless yourself once per day.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    elif not is_self_bless and used >= bdata["daily"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You've used all your {bdata['label']} blessings today.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return

    # Check if receiver already has an active blessing (no stacking)
    with get_db() as conn:
        existing_bless = conn.execute(
            "SELECT blessing_type, expires_at FROM lvl_blessings WHERE user_id=? AND guild_id=? AND expires_at > ?",
            (receiver.id, ctx.guild.id, now)
        ).fetchone()
    if existing_bless:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **{receiver.mention} already has an active blessing.** They can only hold one blessing at a time.",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=8)
        return

    # Apply blessing
    expires = now + timedelta(hours=1)
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lvl_blessings (user_id, guild_id, blessing_type, multiplier, expires_at) VALUES (?,?,?,?,?)",
            (receiver.id, ctx.guild.id, bless_type, bdata["mult"], expires)
        )
        conn.execute(
            "INSERT OR REPLACE INTO lvl_bless_daily (user_id, guild_id, bless_type, used, last_reset) VALUES (?,?,?,?,?)",
            (ctx.author.id, ctx.guild.id, bless_type, used + 1, now if used == 0 else daily[1])
        )
        conn.commit()

    expires_ts = int(expires.timestamp())
    remaining = daily_limit - (used + 1)

    embed = discord.Embed(color=discord.Color.blurple())
    embed.description = (
        f"\u200b\n"
        f"{EMOJI_LVL_ACTION} {ctx.author.mention} granted a {bdata['emoji']} **{bdata['label']}** to {receiver.mention}\n"
        f"\u200b\n"
        f"{EMOJI_LVL_INCREASE} **XP Multiplier Increased**\n"
        f"{EMOJI_LVL_PROGRESS} **{bdata['mult']}x XP** {EMOJI_LVL_TIME} until <t:{expires_ts}:t> (<t:{expires_ts}:R>)\n"
        f"\u200b\n"
        f"{EMOJI_LVL_CAL} **Blessings Remaining Today: {remaining}/{daily_limit}**"
    )
    await ctx.send(embed=embed)

# ---------- !reaction set ----------
def is_elite_or_supreme():
    async def predicate(ctx: commands.Context):
        if not ctx.guild:
            return False
        now = datetime.now(timezone.utc)
        with get_db() as conn:
            tiers = conn.execute(
                "SELECT tier FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND expires_at > ?",
                (ctx.author.id, ctx.guild.id, now)
            ).fetchall()
        tiers = [t[0] for t in tiers]
        if any(t in tiers for t in ("elite", "supreme")):
            return True
        raise commands.CheckFailure("elite_or_supreme")
    return commands.check(predicate)

@bot.group(name="reaction", invoke_without_command=True)
@is_elite_or_supreme()
async def reaction_group(ctx: commands.Context):
    pass

@reaction_group.error
async def reaction_group_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CheckFailure):
        embed = discord.Embed(
            description=f"{EMOJI_LVL_ELITE} **This is an Elite & Supreme perk.**\nYou need an active Elite or Supreme role to use `!reaction` commands.",
            color=discord.Color.gold()
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        await send_then_delete(ctx, embed, delay=8)

@reaction_group.command(name="set")
async def cmd_reaction_set(ctx: commands.Context, *emojis: str):
    """!reaction set [emoji1] [emoji2] ... — saves up to 5 emojis, replaces existing set.
    Elite or Supreme members get these reactions added when someone mentions them."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return

    if not emojis:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Usage:** `!reaction set [emoji1] [emoji2] ...` (up to 5)\nExample: `!reaction set 👑 ✨ 💎`",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return

    if len(emojis) > 5:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can only set up to 5 reaction emojis.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=8)
        return

    # Validate each emoji
    valid = []
    invalid = []
    for e in emojis:
        match = re.match(r"<a?:(\w+):(\d+)>", e)
        if match:
            emoji_id = int(match.group(2))
            server_emoji = discord.utils.get(ctx.guild.emojis, id=emoji_id)
            if server_emoji:
                valid.append(e)
            else:
                invalid.append(e)
        else:
            # Unicode emoji — allow
            valid.append(e)

    if invalid:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **These emojis are not available in this server:** {' '.join(invalid)}",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return

    # Replace all existing reactions with the new set and ensure reactions are enabled
    with get_db() as conn:
        conn.execute("DELETE FROM lvl_reactions WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id))
        for e in valid:
            conn.execute("INSERT INTO lvl_reactions (user_id, guild_id, emoji) VALUES (?,?,?)", (ctx.author.id, ctx.guild.id, e))
        conn.execute(
            "UPDATE lvl_users SET reactions_enabled=1 WHERE user_id=? AND guild_id=?",
            (ctx.author.id, ctx.guild.id)
        )
        conn.commit()

    preview = " ".join(valid)
    embed = discord.Embed(
        description=f"{EMOJI_SUCCESS} **Mention reactions set:** {preview}\nThese will be added whenever someone mentions you.",
        color=discord.Color.green()
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed, delay=8)


@reaction_group.command(name="clear")
async def cmd_reaction_clear(ctx: commands.Context):
    """!reaction clear — removes all your mention reactions."""
    with get_db() as conn:
        conn.execute("DELETE FROM lvl_reactions WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id))
        conn.commit()
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Mention reactions cleared.**", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@reaction_group.command(name="toggle")
async def cmd_reaction_toggle(ctx: commands.Context):
    """!reaction toggle — turn your mention reactions on or off."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    ensure_lvl_user(ctx.author.id, ctx.guild.id)
    udata = get_lvl_user(ctx.author.id, ctx.guild.id)
    current = udata.get("reactions_enabled", 1)
    new_state = 0 if current else 1
    with get_db() as conn:
        conn.execute(
            "UPDATE lvl_users SET reactions_enabled=? WHERE user_id=? AND guild_id=?",
            (new_state, ctx.author.id, ctx.guild.id)
        )
        conn.commit()
    status = "enabled" if new_state else "disabled"
    emoji = EMOJI_SUCCESS if new_state else EMOJI_WARNING
    embed = discord.Embed(
        description=f"{emoji} **Mention reactions {status}.**",
        color=discord.Color.green() if new_state else discord.Color.orange()
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed, delay=5)


# ---------- Admin: !sys addbooster ----------
# !e command group — admin only
@bot.group(name="e", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def e_group(ctx: commands.Context):
    pass

@e_group.error
async def e_group_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **You need the Administrator permission to use `!e` commands.**",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=5)

ADDBOOSTER_TYPES = {
    1: ("dbl_1h",  "1hr Double XP",  EMOJI_LVL_DOUBLE),
    2: ("dbl_12h", "12hr Double XP", EMOJI_LVL_DOUBLE),
    3: ("dbl_24h", "24hr Double XP", EMOJI_LVL_DOUBLE),
    4: ("tri_1h",  "1hr Triple XP",  EMOJI_LVL_TRIPLE),
    5: ("tri_12h", "12hr Triple XP", EMOJI_LVL_TRIPLE),
    6: ("tri_24h", "24hr Triple XP", EMOJI_LVL_TRIPLE),
    7: ("5x_24h",  "24hr 5x XP",     EMOJI_LVL_5X),
    8: ("5x_3d",   "3-Day 5x XP",    EMOJI_LVL_5X),
}

@e_group.command(name="addbooster")
async def cmd_e_addbooster(ctx: commands.Context, btype: int = None, user: discord.Member = None, qty: int = 1):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    if btype is None or user is None or btype not in ADDBOOSTER_TYPES:
        lines = "\n".join(f"**{n}.** {info[1]}" for n, info in ADDBOOSTER_TYPES.items())
        embed = discord.Embed(
            title=f"{EMOJI_ERROR} Usage: `!e addbooster <type> @user [quantity]`",
            description=f"Example: `!e addbooster 1 @eren 3`\n\n{lines}",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=15)
        return
    bkey, blabel, bemoji = ADDBOOSTER_TYPES[btype]
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO lvl_big_boosters (user_id, guild_id, booster_type, quantity) VALUES (?,?,?,0)",
            (user.id, ctx.guild.id, bkey)
        )
        conn.execute(
            "UPDATE lvl_big_boosters SET quantity = quantity + ? WHERE user_id=? AND guild_id=? AND booster_type=?",
            (qty, user.id, ctx.guild.id, bkey)
        )
        conn.commit()
    embed = discord.Embed(
        description=f"{EMOJI_SUCCESS} **Added {qty}x {bemoji} {blabel} to {user.mention}.**",
        color=discord.Color.green()
    )
    await send_then_delete(ctx, embed, delay=5)


@e_group.command(name="removerole")
async def cmd_e_removerole(ctx: commands.Context, user: discord.Member = None):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    if user is None:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Usage:** `!e removerole @user`",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return

    now = datetime.now(timezone.utc)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT tier, expires_at FROM lvl_vip_roles WHERE user_id=? AND guild_id=? ORDER BY expires_at DESC",
            (user.id, ctx.guild.id)
        ).fetchall()

    if not rows:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **{user.mention} has no active tier roles.**",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed)
        return

    TIER_EMOJIS = {"vip": EMOJI_LVL_VIP, "elite": EMOJI_LVL_ELITE, "supreme": EMOJI_LVL_SUPREME}
    TIER_LABELS  = {"vip": "VIP", "elite": "Elite", "supreme": "Supreme"}

    async def do_remove(interaction: discord.Interaction, tier: str, view: discord.ui.View):
        with get_db() as conn:
            conn.execute(
                "DELETE FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND tier=?",
                (user.id, ctx.guild.id, tier)
            )
            dr = conn.execute(
                "SELECT role_id FROM lvl_discord_roles WHERE guild_id=? AND tier=?",
                (ctx.guild.id, tier)
            ).fetchone()
            conn.commit()
        disc_role = ctx.guild.get_role(dr[0]) if dr else None
        if disc_role and disc_role in user.roles:
            try:
                await user.remove_roles(disc_role)
            except Exception:
                pass
        tier_emoji = TIER_EMOJIS.get(tier, "")
        tier_label = TIER_LABELS.get(tier, tier.title())
        done_embed = discord.Embed(
            description=f"{EMOJI_SUCCESS} **Removed {tier_emoji} {tier_label} from {user.mention}.**",
            color=discord.Color.orange()
        )
        done_embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(embed=done_embed, view=view)

    if len(rows) == 1:
        tier, expires_at = rows[0]
        tier_label = TIER_LABELS.get(tier, tier.title())
        tier_emoji = TIER_EMOJIS.get(tier, "")
        expires_ts = int(expires_at.timestamp()) if hasattr(expires_at, "timestamp") else 0
        embed = discord.Embed(
            title=f"{EMOJI_DELETE} **Remove Tier Role**",
            description=(
                f"Remove {tier_emoji} **{tier_label}** from {user.mention}?\n"
                f"Validity expires: <t:{expires_ts}:R>"
            ),
            color=discord.Color.orange()
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        view = discord.ui.View(timeout=30)
        confirm_btn = discord.ui.Button(label="Remove", style=discord.ButtonStyle.danger, emoji=EMOJI_DELETE)
        cancel_btn  = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)

        async def confirm_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(embed=discord.Embed(description=f"{EMOJI_ERROR} **Only the command invoker can confirm.**", color=discord.Color.red()), ephemeral=True)
                return
            await do_remove(interaction, tier, view)

        async def cancel_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(embed=discord.Embed(description=f"{EMOJI_ERROR} **Only the command invoker can cancel.**", color=discord.Color.red()), ephemeral=True)
                return
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(embed=discord.Embed(description="Cancelled.", color=discord.Color.greyple()), view=view)

        confirm_btn.callback = confirm_cb
        cancel_btn.callback  = cancel_cb
        view.add_item(confirm_btn)
        view.add_item(cancel_btn)
        await ctx.send(embed=embed, view=view)
        return

    # Multiple roles — dropdown to pick which to remove
    options = []
    for tier, expires_at in rows:
        tier_label = TIER_LABELS.get(tier, tier.title())
        expires_ts = int(expires_at.timestamp()) if hasattr(expires_at, "timestamp") else 0
        options.append(discord.SelectOption(
            label=tier_label,
            description=f"Expires <t:{expires_ts}:d>",
            value=tier
        ))

    embed = discord.Embed(
        title=f"{EMOJI_DELETE} **Remove Tier Role**",
        description=f"{user.mention} has **{len(rows)} active tier roles**. Select which one to remove:",
        color=discord.Color.orange()
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    view = discord.ui.View(timeout=30)
    select = discord.ui.Select(placeholder="Select a tier role to remove...", options=options, min_values=1, max_values=1)

    async def select_cb(interaction: discord.Interaction):
        if interaction.user.id != ctx.author.id:
            await interaction.response.send_message(embed=discord.Embed(description=f"{EMOJI_ERROR} **Only the command invoker can use this.**", color=discord.Color.red()), ephemeral=True)
            return
        await do_remove(interaction, select.values[0], view)

    select.callback = select_cb
    view.add_item(select)
    await ctx.send(embed=embed, view=view)


@e_group.command(name="removebooster")
async def cmd_e_removebooster(ctx: commands.Context, btype: int = None, user: discord.Member = None, qty: int = 1):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    if btype is None or user is None or btype not in ADDBOOSTER_TYPES:
        lines = "\n".join(f"**{n}.** {info[1]}" for n, info in ADDBOOSTER_TYPES.items())
        embed = discord.Embed(
            title=f"{EMOJI_ERROR} Usage: `!e removebooster <type> @user [quantity]`",
            description=f"Example: `!e removebooster 1 @eren 1`\n\n{lines}",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=15)
        return
    bkey, blabel, bemoji = ADDBOOSTER_TYPES[btype]
    with get_db() as conn:
        row = conn.execute(
            "SELECT quantity FROM lvl_big_boosters WHERE user_id=? AND guild_id=? AND booster_type=?",
            (user.id, ctx.guild.id, bkey)
        ).fetchone()
        current = row[0] if row else 0
        if current <= 0:
            embed = discord.Embed(
                description=f"{EMOJI_ERROR} **{user.mention} has no {blabel} boosters to remove.**",
                color=discord.Color.red()
            )
            await send_then_delete(ctx, embed, delay=5)
            return
        remove = min(qty, current)
        conn.execute(
            "UPDATE lvl_big_boosters SET quantity = quantity - ? WHERE user_id=? AND guild_id=? AND booster_type=?",
            (remove, user.id, ctx.guild.id, bkey)
        )
        conn.commit()
    embed = discord.Embed(
        description=f"{EMOJI_SUCCESS} **Removed {remove}x {bemoji} {blabel} from {user.mention}.** ({current - remove} remaining)",
        color=discord.Color.orange()
    )
    await send_then_delete(ctx, embed, delay=5)


@e_group.command(name="addrole")
async def cmd_e_addrole(ctx: commands.Context, rtype: int = None, user: discord.Member = None, number: int = None, time_unit: str = None):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    ROLE_TYPES = {1: "vip", 2: "elite", 3: "supreme"}
    if rtype is None or user is None or rtype not in ROLE_TYPES or number is None or time_unit is None:
        embed = discord.Embed(
            title=f"{EMOJI_ERROR} Usage: `!e addrole <1-3> @user <number> <m/y>`",
            description=(
                "**1.** VIP · **2.** Elite · **3.** Supreme\n"
                "`m` = months · `y` = years\n\n"
                "**Example:** `!e addrole 2 @user 3 m` — grants Elite for 3 months\n"
                "**Example:** `!e addrole 3 @user 1 y` — grants Supreme for 1 year"
            ),
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=12)
        return
    time_unit = time_unit.lower()
    if time_unit not in ("m", "y"):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Time unit must be `m` (months) or `y` (years).**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=8)
        return
    tier = ROLE_TYPES[rtype]
    now = datetime.now(timezone.utc)
    if time_unit == "m":
        # Add number months
        month = now.month + number
        year = now.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        import calendar as _cal
        day = min(now.day, _cal.monthrange(year, month)[1])
        timed_expiry = now.replace(year=year, month=month, day=day)
    else:
        # Add number years
        timed_expiry = now.replace(year=now.year + number)
    colors = {"vip": 0x57F287, "elite": 0x5865F2, "supreme": 0xFFD700}
    icons = {"vip": EMOJI_LVL_VIP, "elite": EMOJI_LVL_ELITE, "supreme": EMOJI_LVL_SUPREME}
    TIER_PERMS = {
        "vip": discord.Permissions(stream=True, use_soundboard=True, send_voice_messages=True),
        "elite": discord.Permissions(
            stream=True, use_soundboard=True, send_voice_messages=True,
            attach_files=True, create_private_threads=True, add_reactions=True,
        ),
        "supreme": discord.Permissions(
            stream=True, use_soundboard=True, send_voice_messages=True,
            attach_files=True, create_private_threads=True, add_reactions=True,
        ),
    }
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lvl_vip_roles (user_id, guild_id, tier, expires_at) VALUES (?,?,?,?)",
            (user.id, ctx.guild.id, tier, timed_expiry)
        )
        dr = conn.execute(
            "SELECT role_id FROM lvl_discord_roles WHERE guild_id=? AND tier=?",
            (ctx.guild.id, tier)
        ).fetchone()
        role = ctx.guild.get_role(dr[0]) if dr else None
        if not role:
            try:
                role = await ctx.guild.create_role(name=tier.capitalize(), color=discord.Color(colors[tier]))
                if ctx.guild.premium_tier >= 2:
                    icon_url = emoji_to_url(icons[tier])
                    if icon_url:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(icon_url) as resp:
                                if resp.status == 200:
                                    raw = await resp.read()
                                    img = _process_icon_bytes(raw)
                                    await role.edit(icon=img)
                conn.execute(
                    "INSERT OR REPLACE INTO lvl_discord_roles (guild_id, tier, role_id) VALUES (?,?,?)",
                    (ctx.guild.id, tier, role.id)
                )
            except Exception:
                pass
        conn.commit()
    if role:
        try:
            await role.edit(permissions=TIER_PERMS.get(tier, discord.Permissions()))
        except Exception:
            pass
        if role not in user.roles:
            try:
                await user.add_roles(role)
            except Exception:
                pass
    if tier == "supreme":
        try:
            await create_custom_role_for_user(user, ctx.guild, ctx.guild.me)
        except Exception:
            pass
    tier_emoji = {1: EMOJI_LVL_VIP, 2: EMOJI_LVL_ELITE, 3: EMOJI_LVL_SUPREME}[rtype]
    tier_label = {1: "VIP", 2: "Elite", 3: "Supreme"}[rtype]
    duration_label = f"{number} {'month' if time_unit == 'm' else 'year'}{'s' if number != 1 else ''}"
    expiry_ts = int(timed_expiry.timestamp())
    embed = discord.Embed(
        description=(
            f"{EMOJI_SUCCESS} **{user.mention} has been granted {tier_emoji} **{tier_label}**.**\n"
            f"{EMOJI_LVL_CAL} Expires in **{duration_label}** (<t:{expiry_ts}:f>)"
        ),
        color=discord.Color(colors[tier])
    )
    await send_then_delete(ctx, embed, delay=8)


@e_group.command(name="extend")
async def cmd_e_extend(ctx: commands.Context, user: discord.Member = None, pct_str: str = None):
    """!e extend @user <percentage> — grants a temporary XP multiplier boost."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    if not user or not pct_str:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Usage:** `!e extend @user <percentage>`\nExample: `!e extend @eren 100%` gives 2x multiplier for 1h",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return
    try:
        pct = int(pct_str.strip().rstrip("%"))
    except ValueError:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Percentage must be a number, e.g. `100%`.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO lvl_boosters (user_id, guild_id, booster_type, pct, expires_at) VALUES (?,?,?,?,?)",
            (user.id, ctx.guild.id, f"extend_{pct}", pct, expires)
        )
        conn.commit()
    display_mult = 1 + pct / 100
    embed = discord.Embed(
        description=(
            f"{EMOJI_SUCCESS} **Extended {user.mention}'s XP multiplier.**\n"
            f"{EMOJI_LVL_INCREASE} **+{pct}%** ({display_mult:.2f}x) for **1 hour**"
        ),
        color=discord.Color.green()
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed, delay=5)


@e_group.command(name="addcredits")
async def cmd_e_addcredits(ctx: commands.Context, user: discord.Member = None, amount: int = None):
    """!e addcredits @user <amount> — add (or subtract with negative) level credits to a user."""
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed)
        return
    if not user or amount is None:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Usage:** `!e addcredits @user <amount>`\nUse a negative number to subtract.",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=10)
        return
    ensure_lvl_user(user.id, ctx.guild.id)
    with get_db() as conn:
        conn.execute(
            "UPDATE lvl_users SET credits = MAX(0, credits + ?) WHERE user_id=? AND guild_id=?",
            (amount, user.id, ctx.guild.id)
        )
        conn.commit()
        new_bal = conn.execute(
            "SELECT credits FROM lvl_users WHERE user_id=? AND guild_id=?",
            (user.id, ctx.guild.id)
        ).fetchone()[0]
    action = "Added" if amount >= 0 else "Removed"
    color = discord.Color.green() if amount >= 0 else discord.Color.orange()
    embed = discord.Embed(
        description=(
            f"{EMOJI_SUCCESS} **{action} {abs(amount):,}** {EMOJI_LVL_CREDITS} credits "
            f"{'to' if amount >= 0 else 'from'} {user.mention}.\n"
            f"New balance: **{new_bal:,}** {EMOJI_LVL_CREDITS}"
        ),
        color=color
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await send_then_delete(ctx, embed, delay=8)


@e_group.command(name="_help_removed")
async def _cmd_e_help_removed(ctx: commands.Context):
    pass  # !e help has been removed


@bot.command(name="prestige")
async def cmd_prestige(ctx: commands.Context):
    cfg = get_lvl_config(ctx.guild.id)
    if not cfg["enabled"]:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Leveling is not enabled.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5)
        return

    ensure_lvl_user(ctx.author.id, ctx.guild.id)
    udata = get_lvl_user(ctx.author.id, ctx.guild.id)
    level = udata["level"]
    prestige = udata["prestige"]

    # Not at level 100 yet
    if level < 100:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} You need **Level 100** to unlock prestige.\nYou are currently **Level {level}**.",
            color=discord.Color.red()
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        await send_then_delete(ctx, embed, delay=8)
        return

    # Max prestige reached
    if prestige >= 10:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **You have already reached the maximum prestige (10).**",
            color=discord.Color.red()
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        await send_then_delete(ctx, embed, delay=8)
        return

    new_prestige = prestige + 1

    # Give reward
    reward_desc = await _generate_level_reward(ctx.author.id, ctx.guild.id, 100)

    # Reset level, XP, remove all level roles
    with get_db() as conn:
        conn.execute(
            "UPDATE lvl_users SET level=0, xp=0, prestige=? WHERE user_id=? AND guild_id=?",
            (new_prestige, ctx.author.id, ctx.guild.id)
        )
        conn.commit()
        level_roles = conn.execute(
            "SELECT role_id FROM lvl_level_roles WHERE guild_id=?", (ctx.guild.id,)
        ).fetchall()

    for (rid,) in level_roles:
        role_obj = ctx.guild.get_role(rid)
        if role_obj and role_obj in ctx.author.roles:
            try:
                await ctx.author.remove_roles(role_obj, reason="Prestige reset")
            except Exception:
                pass

    # Grant prestige role
    await grant_prestige_role(ctx.guild, ctx.author, new_prestige)

    # Grant 10x XP booster for 2 hours as prestige reward
    prestige_boost_expires = datetime.now(timezone.utc) + timedelta(hours=2)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO lvl_boosters (user_id, guild_id, booster_type, pct, expires_at) VALUES (?,?,?,?,?)",
            (ctx.author.id, ctx.guild.id, "prestige_10x", 900, prestige_boost_expires)
        )
        conn.commit()

    prestige_emoji = PRESTIGE_EMOJIS.get(new_prestige, '')
    embed = discord.Embed(color=discord.Color.gold())
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.description = (
        f"You have unlocked {prestige_emoji} **Prestige {new_prestige}**\n"
        f"\u200b\n"
        f"__{EMOJI_LVL_REWARD} **Reward**__\n"
        f"`-` {reward_desc}\n"
        f"`-` {EMOJI_LVL_5X} **10x XP** for **2 hours**\n"
        f"\u200b\n"
        f"Your level has been reset. XP requirement is now **{new_prestige * 10}% higher**."
    )
    await ctx.send(embed=embed)

# ---------- Background Tasks ----------
@tasks.loop(seconds=60)
async def lvl_vc_xp_loop():
    """Every minute: grant XP to all unmuted VC users."""
    now = datetime.now(timezone.utc)
    for guild in bot.guilds:
        cfg = get_lvl_config(guild.id)
        if not cfg["enabled"]:
            continue
        for vc in guild.voice_channels:
            for member in vc.members:
                if member.bot:
                    continue
                state = member.voice
                if state and not state.self_mute and not state.mute:
                    # Accumulate VC time
                    with get_db() as conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO lvl_vc_time (user_id, guild_id, total_minutes) VALUES (?,?,0)",
                            (member.id, guild.id)
                        )
                        conn.execute(
                            "UPDATE lvl_vc_time SET total_minutes = total_minutes + 1 WHERE user_id=? AND guild_id=?",
                            (member.id, guild.id)
                        )
                        conn.commit()
                    await add_xp(bot, guild, member, 10, source="vc")


@tasks.loop(hours=1)
async def lvl_expiry_loop():
    """Clean up expired boosters, blessings, VIP roles."""
    now = datetime.now(timezone.utc)
    # Collect expired VIP before deleting
    with get_db() as conn:
        conn.execute("DELETE FROM lvl_boosters WHERE expires_at <= ?", (now,))
        conn.execute("DELETE FROM lvl_active_big_booster WHERE expires_at <= ?", (now,))
        conn.execute("DELETE FROM lvl_blessings WHERE expires_at <= ?", (now,))
        expired_vip = conn.execute(
            "SELECT user_id, guild_id, tier FROM lvl_vip_roles WHERE expires_at <= ?", (now,)
        ).fetchall()
        conn.execute("DELETE FROM lvl_vip_roles WHERE expires_at <= ?", (now,))
        conn.commit()
    # Now do async Discord calls outside DB context
    for uid, gid, tier in expired_vip:
        guild_obj = bot.get_guild(gid)
        if not guild_obj:
            continue
        member = guild_obj.get_member(uid)
        with get_db() as conn:
            dr = conn.execute("SELECT role_id FROM lvl_discord_roles WHERE guild_id=? AND tier=?", (gid, tier)).fetchone()
        if dr and member:
            role = guild_obj.get_role(dr[0])
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="VIP expired")
                except Exception:
                    pass
        # If member is gone from server or no longer VC-eligible, clean up their personal VC channel
        still_eligible = member is not None and is_vc_eligible(member, gid)
        if not still_eligible:
            with get_db() as conn:
                vc_row = conn.execute(
                    "SELECT channel_id FROM vc_channels WHERE guild_id=? AND owner_id=?",
                    (gid, uid)
                ).fetchone()
            if vc_row:
                cid = vc_row[0]
                ch = guild_obj.get_channel(cid)
                if ch:
                    try:
                        await ch.delete(reason="VIP tier expired — no longer VC eligible")
                    except Exception:
                        pass
                with get_db() as conn:
                    conn.execute("DELETE FROM vc_permissions WHERE channel_id=?", (cid,))
                    conn.execute("DELETE FROM vc_deafened WHERE channel_id=?", (cid,))
                    conn.execute("DELETE FROM vc_muted WHERE channel_id=?", (cid,))
                    conn.execute("DELETE FROM vc_channels WHERE channel_id=?", (cid,))
                    conn.commit()


# ---------- Event Hooks ----------
async def on_message_lvl(message: discord.Message):
    """Called from on_message to handle chat XP."""
    if message.author.bot or not message.guild:
        return
    cfg = get_lvl_config(message.guild.id)
    if not cfg["enabled"]:
        return
    # Auto-react to mentions — runs on ALL channels, no channel filter (only for Elite or Supreme)
    now_react = datetime.now(timezone.utc)
    for mention in message.mentions:
        if mention.bot:
            continue
        with get_db() as conn:
            tiers = conn.execute(
                "SELECT tier FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND expires_at > ?",
                (mention.id, message.guild.id, now_react)
            ).fetchall()
            tier_names = [t[0] for t in tiers]
            if not any(t in tier_names for t in ("elite", "supreme")):
                continue
            # Check if user has reactions enabled
            rxn_row = conn.execute(
                "SELECT reactions_enabled FROM lvl_users WHERE user_id=? AND guild_id=?",
                (mention.id, message.guild.id)
            ).fetchone()
            if rxn_row and rxn_row[0] == 0:
                continue
            emojis = conn.execute(
                "SELECT emoji FROM lvl_reactions WHERE user_id=? AND guild_id=?",
                (mention.id, message.guild.id)
            ).fetchall()
        for (e,) in emojis:
            try:
                await message.add_reaction(e)
            except Exception:
                pass

    # Channel filter — XP gain only (reactions above already ran on all channels)
    if cfg["xp_channel_ids"]:
        allowed = [int(x) for x in cfg["xp_channel_ids"].split(",") if x.strip().isdigit()]
        if allowed and message.channel.id not in allowed:
            return

    # Cooldown: 60 seconds per user (XP only)
    ensure_lvl_user(message.author.id, message.guild.id)
    udata = get_lvl_user(message.author.id, message.guild.id)
    now = datetime.now(timezone.utc)
    last = udata["last_chat_xp"]
    if last and (now - last).total_seconds() < 60:
        return
    with get_db() as conn:
        conn.execute("UPDATE lvl_users SET last_chat_xp=? WHERE user_id=? AND guild_id=?",
                     (now, message.author.id, message.guild.id))
        conn.commit()
    xp = random.randint(5, 15)
    await add_xp(bot, message.guild, message.author, xp, source="chat")


async def on_voice_state_lvl(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """Track VC time start/stop on mute/unmute/join/leave."""
    if member.bot:
        return
    now = datetime.now(timezone.utc)
    guild = member.guild
    cfg = get_lvl_config(guild.id)
    if not cfg["enabled"]:
        return

    was_active = before.channel is not None and not before.self_mute and not before.mute
    is_active = after.channel is not None and not after.self_mute and not after.mute

    if was_active and not is_active:
        # User left or muted — session ends (XP handled by per-minute loop already)
        pass
    if not was_active and is_active:
        # User joined unmuted — nothing to do, loop handles it
        pass


# ==========================================
# ---------- Voice Channel (VC) System ----------
# ==========================================

import json as _vc_json

def is_vc_eligible(member: discord.Member, guild_id: int) -> bool:
    # Admins are NOT automatically eligible — they must have an actual VIP tier,
    # be an active server booster, or have explicit vc_admin_perms granted.
    if member.premium_since is not None:
        return True
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        vip_rows = conn.execute(
            "SELECT tier FROM lvl_vip_roles WHERE user_id=? AND guild_id=? AND expires_at>?",
            (member.id, guild_id, now)
        ).fetchall()
        for (tier,) in vip_rows:
            # Cross-check: the member must actually hold the matching Discord role.
            dr = conn.execute(
                "SELECT role_id FROM lvl_discord_roles WHERE guild_id=? AND tier=?",
                (guild_id, tier)
            ).fetchone()
            if dr:
                role = member.guild.get_role(dr[0])
                if role and role in member.roles:
                    return True
            else:
                # No Discord role configured for this tier — trust the DB record alone.
                return True
        perm = conn.execute(
            "SELECT 1 FROM vc_admin_perms WHERE user_id=? AND guild_id=?",
            (member.id, guild_id)
        ).fetchone()
    return perm is not None


def get_member_vc_tier(member: discord.Member, guild_id: int) -> Optional[str]:
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        row = conn.execute(
            """SELECT tier FROM lvl_vip_roles
               WHERE user_id=? AND guild_id=? AND expires_at>?
               ORDER BY CASE tier WHEN 'supreme' THEN 3 WHEN 'elite' THEN 2 ELSE 1 END DESC
               LIMIT 1""",
            (member.id, guild_id, now)
        ).fetchone()
    if row:
        return row[0]
    if member.premium_since is not None:
        return 'booster'
    return None


def get_user_vc(member: discord.Member, guild: discord.Guild) -> Optional[discord.VoiceChannel]:
    if not (member.voice and member.voice.channel):
        return None
    vc = member.voice.channel
    with get_db() as conn:
        row = conn.execute("SELECT owner_id FROM vc_channels WHERE channel_id=?", (vc.id,)).fetchone()
    if row and row[0] == member.id:
        return vc
    return None


def build_vc_help_embed() -> discord.Embed:
    embed = discord.Embed(color=0x2B2D31)
    embed.description = (
        "<a:setting:1511112923576271023> : **Customize Your Channel With Commands**\n\n"
        "<:pen:1497406274281934978> **!vc name <name>**\n"
        "<:extend_end:1511143598664712343> Add a name to your channel as you wish\n\n"
        "<:lock:1511519812344479946> **!vc lock / unlock**\n"
        "<:extend_end:1511143598664712343> Make Your Voice Channel Private/Public\n\n"
        "<:invite:1511519948483334174> **!vc perm @member/username/id**\n"
        "-# <:extend_end:1511143598664712343> If you have locked your channel, don't forget to give permission who can join! Use **!vc unperm** to remove\n\n"
        "<:limit:1511520065504415834> **!vc limit <number>**\n"
        "<:extend_end:1511143598664712343> Set how many people can join your VC (max 25)\n\n"
        "<:deaf:1511520166553587774> **!vc deaf @member**\n"
        "<:extend_end:1511143598664712343> Deafen a member in VC by mentioning them\n"
        "-# Remove with **!vc undeaf**\n\n"
        "<:invite:1511519948483334174> **!vc invite @member**\n"
        "<:extend_end:1511143598664712343> Invite a member to your VC\n"
        "-# They must be a server member otherwise it will fail\n\n"
        "<:kick:1511532834807091230> **!vc kick @member**\n"
        "<:extend_end:1511143598664712343> Remove a member from your voice channel\n\n"
        "<a:mute:1511532591579402333> **!vc mute @member**\n"
        "<:extend_con:1488087744843481098> Mute a member by mentioning them\n"
        "<:extend_end:1511143598664712343> Unmute with **!vc unmute**\n\n"
        "<:vc_hide:1511920345085513859> **!vc hide / unhide**\n"
        "<:extend_end:1511143598664712343> Hide your channel from everyone except permitted members\n\n"
        "<:vc_status:1511920421568643133> **!vc status <text>**\n"
        "<:extend_end:1511143598664712343> Add a status for your custom channel\n\n"
        "<:gift:1511114423186751518> **!vc perks**\n"
        "<:extend_end:1511143598664712343> See what access you have within your channel\n\n"
        "-# <:info:1511112351909281904> Your channel will be gone after you leave (unless you have Supreme). "
        "To keep your customization when you rejoin, use **!vc own**\n"
        "-# Use **!vc delete** while in your voice channel to remove ownership"
    )
    return embed


def build_vc_perks_embed() -> discord.Embed:
    embed = discord.Embed(color=0x2B2D31)
    embed.description = (
        "<:reward:1509889693762977813> __**Channel Perks**__\n\n"
        "<:vc_owner:1511920272977039531>  Customizable channel\n\n"
        "<:gift:1511114423186751518> Access to soundboard\n\n"
        "<:gift:1511114423186751518> Access to streaming (camera)\n\n"
        "<:gift:1511114423186751518> Access to external sounds"
    )
    return embed


async def _apply_vc_overwrites(vc: discord.VoiceChannel, settings_row, guild: discord.Guild):
    if not settings_row:
        return
    _ch_name, is_locked, is_hidden, user_limit, _status, saved_perms_json, _own = settings_row
    overwrites = dict(vc.overwrites)
    if is_hidden:
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False, connect=False)
    elif is_locked:
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=True, connect=False)
    if saved_perms_json:
        for uid in _vc_json.loads(saved_perms_json):
            m = guild.get_member(uid)
            if m:
                overwrites[m] = discord.PermissionOverwrite(view_channel=True, connect=True)
    try:
        await vc.edit(overwrites=overwrites, user_limit=user_limit or 0)
    except Exception:
        pass


async def on_voice_state_vc(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return
    guild = member.guild
    with get_db() as conn:
        hub_row = conn.execute(
            "SELECT hub_channel_id, category_id FROM vc_hub WHERE guild_id=?", (guild.id,)
        ).fetchone()
    if not hub_row:
        return
    hub_id, category_id = hub_row

    # ── User joined hub ────────────────────────────────────────────────────
    if after.channel and after.channel.id == hub_id:
        if not is_vc_eligible(member, guild.id):
            try:
                await member.move_to(None)
            except Exception:
                pass
            try:
                embed = discord.Embed(
                    description=f"{EMOJI_ERROR} **You need VIP, Elite, Supreme or Server Booster to use Donor-Join.**",
                    color=discord.Color.red()
                )
                await member.send(embed=embed)
            except Exception:
                pass
            return

        # Supreme: redirect to existing permanent channel
        with get_db() as conn:
            perm_row = conn.execute(
                "SELECT channel_id FROM vc_channels WHERE guild_id=? AND owner_id=? AND is_permanent=1",
                (guild.id, member.id)
            ).fetchone()
        if perm_row:
            ch = guild.get_channel(perm_row[0])
            if ch:
                try:
                    await member.move_to(ch)
                except Exception:
                    pass
                return
            with get_db() as conn:
                conn.execute("DELETE FROM vc_channels WHERE channel_id=?", (perm_row[0],))
                conn.commit()

        tier = get_member_vc_tier(member, guild.id)
        is_supreme = (tier == 'supreme')

        with get_db() as conn:
            settings_row = conn.execute(
                "SELECT channel_name, is_locked, is_hidden, user_limit, status, saved_perms, has_ownership "
                "FROM vc_settings WHERE user_id=? AND guild_id=?",
                (member.id, guild.id)
            ).fetchone()
        has_ownership = bool(settings_row and settings_row[6])

        channel_name = settings_row[0] if (settings_row and settings_row[0]) else f"{member.display_name}'s Channel"

        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
            member: discord.PermissionOverwrite(
                view_channel=True, connect=True, manage_channels=True,
                move_members=True, mute_members=True, deafen_members=True,
                use_soundboard=True, stream=True, use_external_sounds=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, connect=True, manage_channels=True,
                move_members=True, mute_members=True, deafen_members=True
            ),
        }

        try:
            vc = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                user_limit=settings_row[3] if settings_row else 0,
            )
        except Exception as exc:
            print(f"[vc] Failed to create channel for {member}: {exc}")
            return

        await _apply_vc_overwrites(vc, settings_row, guild)

        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO vc_channels (channel_id, guild_id, owner_id, is_permanent, has_ownership) "
                "VALUES (?,?,?,?,?)",
                (vc.id, guild.id, member.id, 1 if is_supreme else 0, 1 if has_ownership else 0)
            )
            if settings_row and settings_row[5]:
                for uid in _vc_json.loads(settings_row[5]):
                    conn.execute("INSERT OR IGNORE INTO vc_permissions (channel_id, user_id) VALUES (?,?)", (vc.id, uid))
            conn.commit()

        try:
            await member.move_to(vc)
        except Exception:
            pass

        try:
            await vc.send(content=member.mention, embed=build_vc_help_embed())
        except Exception:
            pass

    # ── User left a personal VC ────────────────────────────────────────────
    if before.channel and before.channel.id != hub_id:
        with get_db() as conn:
            ch_row = conn.execute(
                "SELECT owner_id, is_permanent, has_ownership FROM vc_channels WHERE channel_id=?",
                (before.channel.id,)
            ).fetchone()
        if not ch_row:
            return
        _owner_id, is_permanent, _has_own = ch_row

        if is_permanent:
            return  # Supreme: channel stays

        if len(before.channel.members) > 0:
            return  # Still occupied

        try:
            await before.channel.delete(reason="Custom VC — empty, temporary channel removed")
        except Exception:
            pass
        with get_db() as conn:
            conn.execute("DELETE FROM vc_channels WHERE channel_id=?", (before.channel.id,))
            conn.execute("DELETE FROM vc_permissions WHERE channel_id=?", (before.channel.id,))
            conn.execute("DELETE FROM vc_deafened WHERE channel_id=?", (before.channel.id,))
            conn.execute("DELETE FROM vc_muted WHERE channel_id=?", (before.channel.id,))
            conn.commit()


# ── !vc command group ──────────────────────────────────────────────────────

@bot.group(name="vc", invoke_without_command=True)
async def vc_group(ctx: commands.Context):
    await ctx.send(embed=build_vc_help_embed())


@vc_group.command(name="help")
async def cmd_vc_help(ctx: commands.Context):
    await ctx.send(embed=build_vc_help_embed())


@vc_group.command(name="perks")
async def cmd_vc_perks(ctx: commands.Context):
    await ctx.send(embed=build_vc_perks_embed())


@vc_group.command(name="name")
async def cmd_vc_name(ctx: commands.Context, *, name: str = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not name:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc name <name>`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    try:
        await vc.edit(name=name)
    except Exception as e:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed to rename: {e}**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    embed = discord.Embed(description=f"<:pen:1497406274281934978> **Channel renamed to `{name}`.**", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="lock")
async def cmd_vc_lock(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    overwrites = dict(vc.overwrites)
    overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(view_channel=True, connect=False)
    try:
        await vc.edit(overwrites=overwrites)
    except Exception:
        pass
    embed = discord.Embed(description=f"<:lock:1511519812344479946> **Channel locked. Use `!vc perm @user` to allow members in.**", color=discord.Color.orange())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="unlock")
async def cmd_vc_unlock(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    overwrites = dict(vc.overwrites)
    overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(view_channel=True, connect=True)
    try:
        await vc.edit(overwrites=overwrites)
    except Exception:
        pass
    embed = discord.Embed(description=f"<:lock:1511519812344479946> **Channel unlocked — anyone can join.**", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="perm")
async def cmd_vc_perm(ctx: commands.Context, user: discord.Member = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc perm @user`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    overwrites = dict(vc.overwrites)
    overwrites[user] = discord.PermissionOverwrite(view_channel=True, connect=True)
    try:
        await vc.edit(overwrites=overwrites)
    except Exception:
        pass
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO vc_permissions (channel_id, user_id) VALUES (?,?)", (vc.id, user.id))
        conn.commit()
    embed = discord.Embed(description=f"<:invite:1511519948483334174> **{user.mention} can now join your channel.**", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="unperm")
async def cmd_vc_unperm(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    with get_db() as conn:
        rows = conn.execute("SELECT user_id FROM vc_permissions WHERE channel_id=?", (vc.id,)).fetchall()
    if not rows:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **No one has permission. Use `!vc perm @user` to give access.**",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=8); return

    options = []
    for (uid,) in rows:
        m = ctx.guild.get_member(uid)
        label = m.display_name if m else str(uid)
        options.append(discord.SelectOption(label=label[:100], value=str(uid)))

    select = discord.ui.Select(placeholder="Select a permitted user...", options=options[:25])

    async def select_cb(sel_inter: discord.Interaction):
        sel_uid = int(select.values[0])
        sel_m = ctx.guild.get_member(sel_uid)
        sel_name = sel_m.display_name if sel_m else str(sel_uid)

        remove_btn = discord.ui.Button(label="Remove Permission", style=discord.ButtonStyle.danger, emoji=EMOJI_DELETE)
        transfer_btn = discord.ui.Button(label="Transfer Ownership", style=discord.ButtonStyle.primary, emoji=EMOJI_USER)
        close_btn = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary)

        async def remove_cb(btn_inter: discord.Interaction):
            ow2 = dict(vc.overwrites)
            if sel_m and sel_m in ow2:
                del ow2[sel_m]
            try:
                await vc.edit(overwrites=ow2)
            except Exception:
                pass
            with get_db() as conn:
                conn.execute("DELETE FROM vc_permissions WHERE channel_id=? AND user_id=?", (vc.id, sel_uid))
                conn.commit()
            e = discord.Embed(description=f"{EMOJI_SUCCESS} **Removed {sel_name}'s permission.**", color=discord.Color.green())
            await btn_inter.response.edit_message(embed=e, view=None)

        async def transfer_cb(btn_inter: discord.Interaction):
            if not sel_m:
                e = discord.Embed(description=f"{EMOJI_ERROR} **User not found in server.**", color=discord.Color.red())
                await btn_inter.response.edit_message(embed=e, view=None); return
            with get_db() as conn:
                conn.execute("UPDATE vc_channels SET owner_id=? WHERE channel_id=?", (sel_uid, vc.id))
                conn.execute("INSERT OR IGNORE INTO vc_permissions (channel_id, user_id) VALUES (?,?)", (vc.id, ctx.author.id))
                conn.commit()
            ow2 = dict(vc.overwrites)
            ow2[sel_m] = discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True)
            ow2[ctx.author] = discord.PermissionOverwrite(view_channel=True, connect=True)
            try:
                await vc.edit(overwrites=ow2)
            except Exception:
                pass
            e = discord.Embed(description=f"{EMOJI_SUCCESS} **Ownership transferred to {sel_m.mention}.**", color=discord.Color.green())
            await btn_inter.response.edit_message(embed=e, view=None)

        async def close_cb(btn_inter: discord.Interaction):
            await btn_inter.response.edit_message(view=None)

        remove_btn.callback = remove_cb
        transfer_btn.callback = transfer_cb
        close_btn.callback = close_cb

        confirm_embed = discord.Embed(
            description=f"**What do you want to do with {sel_name}'s permission?**",
            color=discord.Color.blurple()
        )
        av = discord.ui.View(timeout=30)
        av.add_item(remove_btn); av.add_item(transfer_btn); av.add_item(close_btn)
        await sel_inter.response.edit_message(embed=confirm_embed, view=av)

    select.callback = select_cb
    sv = discord.ui.View(timeout=60)
    sv.add_item(select)
    e = discord.Embed(title="<:invite:1511519948483334174> Permitted Members", description="Select a member to manage.", color=discord.Color.blurple())
    await ctx.send(embed=e, view=sv)


@vc_group.command(name="limit")
async def cmd_vc_limit(ctx: commands.Context, limit: int = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if limit is None or not (0 <= limit <= 99):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc limit <0-99>` (0 = unlimited)", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    try:
        await vc.edit(user_limit=limit)
    except Exception:
        pass
    msg = f"**Channel limit set to {limit} users.**" if limit > 0 else "**Channel limit removed (unlimited).**"
    embed = discord.Embed(description=f"<:limit:1511520065504415834> {msg}", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="deaf")
async def cmd_vc_deaf(ctx: commands.Context, user: discord.Member = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc deaf @user`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if user == ctx.author:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can't deafen yourself.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    try:
        await user.edit(deafen=True)
    except Exception as exc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed: {exc}**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO vc_deafened (channel_id, user_id) VALUES (?,?)", (vc.id, user.id))
        conn.commit()
    embed = discord.Embed(description=f"<:deaf:1511520166553587774> **{user.mention} has been deafened.**", color=discord.Color.orange())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="undeaf")
async def cmd_vc_undeaf(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    with get_db() as conn:
        rows = conn.execute("SELECT user_id FROM vc_deafened WHERE channel_id=?", (vc.id,)).fetchall()
    if not rows:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No one is currently deafened.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5); return
    options = [discord.SelectOption(label=(ctx.guild.get_member(uid) or type('x', (), {'display_name': str(uid)})()).display_name[:100], value=str(uid)) for (uid,) in rows]
    select = discord.ui.Select(placeholder="Select user to undeafen...", options=options[:25])

    async def cb(si: discord.Interaction):
        uid = int(select.values[0])
        m = ctx.guild.get_member(uid)
        if m:
            try:
                await m.edit(deafen=False)
            except Exception:
                pass
        with get_db() as conn:
            conn.execute("DELETE FROM vc_deafened WHERE channel_id=? AND user_id=?", (vc.id, uid))
            conn.commit()
        name = m.display_name if m else str(uid)
        e = discord.Embed(description=f"<:deaf:1511520166553587774> **{name} has been undeafened.**", color=discord.Color.green())
        await si.response.edit_message(embed=e, view=None)

    select.callback = cb
    v = discord.ui.View(timeout=30); v.add_item(select)
    e = discord.Embed(title="<:deaf:1511520166553587774> Deafened Members", description="Select a member to undeafen.", color=discord.Color.blurple())
    await ctx.send(embed=e, view=v)


@vc_group.command(name="invite")
async def cmd_vc_invite(ctx: commands.Context, user: discord.Member = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc invite @user`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if user == ctx.author:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can't mention yourself.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if user.bot:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can't invite bots.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    # Check if invited user is available (not offline/invisible)
    if user.status == discord.Status.offline:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **{user.display_name} is currently unavailable.**",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=6); return
    # Auto-permit so they can join if locked
    ow = dict(vc.overwrites)
    ow[user] = discord.PermissionOverwrite(view_channel=True, connect=True)
    try:
        await vc.edit(overwrites=ow)
    except Exception:
        pass
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO vc_permissions (channel_id, user_id) VALUES (?,?)", (vc.id, user.id))
        conn.commit()
    vc_link = f"https://discord.com/channels/{ctx.guild.id}/{vc.id}"
    join_btn = discord.ui.Button(label="Join", style=discord.ButtonStyle.link, url=vc_link, emoji="<:tring:1511928270894006342>")
    inv_view = discord.ui.View(); inv_view.add_item(join_btn)
    inv_embed = discord.Embed(color=0xFFD700)
    inv_embed.description = (
        f"<a:daily_perk:1510988210023436348> ***Hello dear, {user.mention}\n"
        f"You were invited by {ctx.author.mention} to join and talk in*** {vc.mention}\n\n"
        f"<:tring:1511928270894006342> Click below to join"
    )
    # Send to the current text channel where the command was invoked
    await ctx.send(content=user.mention, embed=inv_embed, view=inv_view)


@vc_group.command(name="kick")
async def cmd_vc_kick(ctx: commands.Context, user: discord.Member = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc kick @user`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if user == ctx.author:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can't kick yourself.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not (user.voice and user.voice.channel and user.voice.channel.id == vc.id):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **{user.display_name} is not in your channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    try:
        await user.move_to(None)
    except Exception as exc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed: {exc}**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    embed = discord.Embed(description=f"<:kick:1511532834807091230> **{user.mention} was removed from your channel.**", color=discord.Color.orange())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="mute")
async def cmd_vc_mute(ctx: commands.Context, user: discord.Member = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc mute @user`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    try:
        await user.edit(mute=True)
    except Exception as exc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed: {exc}**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO vc_muted (channel_id, user_id) VALUES (?,?)", (vc.id, user.id))
        conn.commit()
    embed = discord.Embed(description=f"<a:mute:1511532591579402333> **{user.mention} has been muted.**", color=discord.Color.orange())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="unmute")
async def cmd_vc_unmute(ctx: commands.Context, user: discord.Member = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc unmute @user`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    try:
        await user.edit(mute=False)
    except Exception:
        pass
    with get_db() as conn:
        conn.execute("DELETE FROM vc_muted WHERE channel_id=? AND user_id=?", (vc.id, user.id))
        conn.commit()
    embed = discord.Embed(description=f"<a:mute:1511532591579402333> **{user.mention} has been unmuted.**", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="status")
async def cmd_vc_status(ctx: commands.Context, *, status: str = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not status:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc status <text>`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    try:
        await vc.edit(status=status)
    except Exception as exc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed: {exc}**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    embed = discord.Embed(description=f"<:vc_status:1511920421568643133> **Status set to `{status}`.**", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="hide")
async def cmd_vc_hide(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    ow = dict(vc.overwrites)
    ow[ctx.guild.default_role] = discord.PermissionOverwrite(view_channel=False, connect=False)
    try:
        await vc.edit(overwrites=ow)
    except Exception:
        pass
    embed = discord.Embed(description=f"<:vc_hide:1511920345085513859> **Channel hidden — only permitted members can see it.**", color=discord.Color.orange())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="unhide")
async def cmd_vc_unhide(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    ow = dict(vc.overwrites)
    ow[ctx.guild.default_role] = discord.PermissionOverwrite(view_channel=True, connect=True)
    try:
        await vc.edit(overwrites=ow)
    except Exception:
        pass
    embed = discord.Embed(description=f"<:vc_hide:1511920345085513859> **Channel is visible again to everyone.**", color=discord.Color.green())
    await send_then_delete(ctx, embed, delay=5)


@vc_group.command(name="own")
async def cmd_vc_own(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    default_ow = vc.overwrites_for(ctx.guild.default_role)
    is_locked = (default_ow.connect is False)
    is_hidden = (default_ow.view_channel is False)
    with get_db() as conn:
        rows = conn.execute("SELECT user_id FROM vc_permissions WHERE channel_id=?", (vc.id,)).fetchall()
        perm_ids = [r[0] for r in rows]
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO vc_settings
               (user_id, guild_id, channel_name, is_locked, is_hidden, user_limit, status, saved_perms, has_ownership)
               VALUES (?,?,?,?,?,?,?,?,1)""",
            (ctx.author.id, ctx.guild.id, vc.name,
             1 if is_locked else 0, 1 if is_hidden else 0,
             vc.user_limit, "", _vc_json.dumps(perm_ids))
        )
        conn.execute("UPDATE vc_channels SET has_ownership=1 WHERE channel_id=?", (vc.id,))
        conn.commit()
    embed = discord.Embed(
        description=(
            f"{EMOJI_SUCCESS} **Ownership saved!**\n"
            f"Your channel settings are stored. Next time you join **Donor-Join**, "
            f"your channel will be recreated with these exact settings."
        ),
        color=discord.Color.green()
    )
    await send_then_delete(ctx, embed, delay=8)


@vc_group.command(name="transfer")
async def cmd_vc_transfer(ctx: commands.Context, user: discord.Member = None):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Usage:** `!vc transfer @user`", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if user == ctx.author:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can't transfer ownership to yourself.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if user.bot:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You can't transfer ownership to a bot.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    with get_db() as conn:
        conn.execute("UPDATE vc_channels SET owner_id=? WHERE channel_id=?", (user.id, vc.id))
        conn.execute("INSERT OR IGNORE INTO vc_permissions (channel_id, user_id) VALUES (?,?)", (vc.id, ctx.author.id))
        conn.commit()
    ow = dict(vc.overwrites)
    ow[user] = discord.PermissionOverwrite(
        view_channel=True, connect=True, manage_channels=True,
        move_members=True, mute_members=True, deafen_members=True,
        use_soundboard=True, stream=True, use_external_sounds=True
    )
    ow[ctx.author] = discord.PermissionOverwrite(view_channel=True, connect=True)
    try:
        await vc.edit(overwrites=ow)
    except Exception:
        pass
    embed = discord.Embed(
        description=f"{EMOJI_SUCCESS} **Ownership transferred to {user.mention}.** They now control this channel.",
        color=discord.Color.green()
    )
    await send_then_delete(ctx, embed, delay=6)


@vc_group.command(name="delete")
async def cmd_vc_delete(ctx: commands.Context):
    vc = get_user_vc(ctx.author, ctx.guild)
    if not vc:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **You must be in your own voice channel.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    with get_db() as conn:
        conn.execute("DELETE FROM vc_settings WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id))
        conn.execute("UPDATE vc_channels SET has_ownership=0, is_permanent=0 WHERE channel_id=?", (vc.id,))
        conn.commit()
    embed = discord.Embed(
        description=(
            f"{EMOJI_SUCCESS} **Ownership removed.**\n"
            f"Your customization has been cleared. When you leave, the channel will be deleted "
            f"and settings reset to default next time."
        ),
        color=discord.Color.orange()
    )
    await send_then_delete(ctx, embed, delay=8)


# ── !e vc admin subgroup ───────────────────────────────────────────────────

@e_group.group(name="vc", invoke_without_command=True)
async def e_vc_group(ctx: commands.Context):
    embed = discord.Embed(title=f"{EMOJI_HAMMER} **!e vc — Admin Voice Commands**", color=discord.Color.blurple())
    embed.add_field(name="`!e vc setup [category_id]`", value="Create the **Donor-Join** hub VC", inline=False)
    embed.add_field(name="`!e vc disable`", value="Delete hub and disable VC system", inline=False)
    embed.add_field(name="`!e vc perm @user <t/p>`", value="Grant VC access: **t** = temporary · **p** = permanent", inline=False)
    await send_then_delete(ctx, embed, delay=15)


@e_vc_group.command(name="setup")
async def cmd_e_vc_setup(ctx: commands.Context):
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return

    with get_db() as conn:
        existing = conn.execute("SELECT hub_channel_id FROM vc_hub WHERE guild_id=?", (ctx.guild.id,)).fetchone()
    if existing:
        ch = ctx.guild.get_channel(existing[0])
        if ch:
            embed = discord.Embed(description=f"{EMOJI_WARNING} **Donor-Join already exists: {ch.mention}**", color=discord.Color.orange())
            await send_then_delete(ctx, embed, delay=5); return

    # Build category options for the dropdown
    categories = [c for c in ctx.guild.channels if isinstance(c, discord.CategoryChannel)]
    options = [discord.SelectOption(label="📋 No Category (top-level)", value="0")]
    for cat in categories[:24]:
        options.append(discord.SelectOption(label=cat.name[:100], value=str(cat.id)))

    setup_embed = discord.Embed(
        title="<:vc:1511928270894006342> **VC Setup**",
        description=(
            "Select the **category** where all voice channels will be created.\n\n"
            "The bot will create:\n"
            "• **Donor-Join** — hub voice channel\n"
            "VIP, Elite, Supreme members & Server Boosters can join to get their own personal VC.\n\n"
            "Only **1 category** can be selected."
        ),
        color=discord.Color.blurple()
    )
    setup_embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

    view = discord.ui.View(timeout=60)
    select = discord.ui.Select(
        placeholder="Select a category for voice channels...",
        options=options,
        min_values=1,
        max_values=1
    )

    async def select_cb(interaction: discord.Interaction):
        if interaction.user.id != ctx.author.id:
            await interaction.response.send_message(f"{EMOJI_ERROR} Only the command invoker can use this.", ephemeral=True)
            return
        cat_id_val = select.values[0]
        category = None
        if cat_id_val != "0":
            category = ctx.guild.get_channel(int(cat_id_val))

        for item in view.children:
            item.disabled = True

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
            ctx.guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True, manage_channels=True),
        }
        with get_db() as conn:
            disc_roles = conn.execute("SELECT role_id FROM lvl_discord_roles WHERE guild_id=?", (ctx.guild.id,)).fetchall()
        for (rid,) in disc_roles:
            role = ctx.guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, connect=True)
        if ctx.guild.premium_subscriber_role:
            overwrites[ctx.guild.premium_subscriber_role] = discord.PermissionOverwrite(view_channel=True, connect=True)

        try:
            hub_vc = await ctx.guild.create_voice_channel(
                name="Donor-Join",
                category=category,
                overwrites=overwrites,
            )
        except Exception as exc:
            err_embed = discord.Embed(description=f"{EMOJI_ERROR} **Failed to create channel: {exc}**", color=discord.Color.red())
            await interaction.response.edit_message(embed=err_embed, view=view)
            return

        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO vc_hub (guild_id, hub_channel_id, category_id) VALUES (?,?,?)",
                (ctx.guild.id, hub_vc.id, category.id if category else hub_vc.category_id)
            )
            conn.commit()

        done_embed = discord.Embed(
            description=(
                f"{EMOJI_SUCCESS} **Donor-Join created: {hub_vc.mention}**\n\n"
                f"VIP, Elite, Supreme tier members and Server Boosters can join. "
                f"When they do, the bot will automatically create a personal VC for them."
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=done_embed, view=view)

    select.callback = select_cb
    view.add_item(select)

    cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=BTN_BACK)
    async def cancel_cb(interaction: discord.Interaction):
        if interaction.user.id != ctx.author.id:
            await interaction.response.send_message(f"{EMOJI_ERROR} Only the command invoker can use this.", ephemeral=True)
            return
        for item in view.children:
            item.disabled = True
        cancel_embed = discord.Embed(description="VC setup cancelled.", color=discord.Color.greyple())
        await interaction.response.edit_message(embed=cancel_embed, view=view)
    cancel_btn.callback = cancel_cb
    view.add_item(cancel_btn)

    await ctx.send(embed=setup_embed, view=view)


@e_vc_group.command(name="disable")
async def cmd_e_vc_disable(ctx: commands.Context):
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    with get_db() as conn:
        row = conn.execute("SELECT hub_channel_id FROM vc_hub WHERE guild_id=?", (ctx.guild.id,)).fetchone()
    if not row:
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No Donor-Join hub is configured.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    ch = ctx.guild.get_channel(row[0])
    if ch:
        try:
            await ch.delete(reason="VC system disabled by admin")
        except Exception:
            pass
    with get_db() as conn:
        conn.execute("DELETE FROM vc_hub WHERE guild_id=?", (ctx.guild.id,))
        conn.commit()
    embed = discord.Embed(description=f"{EMOJI_SUCCESS} **Donor-Join hub removed. VC system is now disabled.**", color=discord.Color.orange())
    await send_then_delete(ctx, embed, delay=5)


@e_vc_group.command(name="perm")
async def cmd_e_vc_perm(ctx: commands.Context, user: discord.Member = None, ptype: str = "p"):
    if not await is_admin_or_whitelisted(ctx.author, "setup", ctx.guild):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **No permission.**", color=discord.Color.red())
        await send_then_delete(ctx, embed); return
    if not user:
        embed = discord.Embed(
            description=f"{EMOJI_ERROR} **Usage:** `!e vc perm @user <t/p>`\n**t** = temporary · **p** = permanent",
            color=discord.Color.red()
        )
        await send_then_delete(ctx, embed, delay=8); return
    ptype = ptype.lower()
    if ptype not in ('t', 'p'):
        embed = discord.Embed(description=f"{EMOJI_ERROR} **Type must be `t` or `p`.**", color=discord.Color.red())
        await send_then_delete(ctx, embed, delay=5); return
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO vc_admin_perms (user_id, guild_id, perm_type) VALUES (?,?,?)",
            (user.id, ctx.guild.id, ptype)
        )
        conn.commit()
    label = "**temporary** (this session)" if ptype == 't' else "**permanent**"
    embed = discord.Embed(
        description=f"{EMOJI_SUCCESS} **{user.mention} can now join Donor-Join** ({label}).",
        color=discord.Color.green()
    )
    await send_then_delete(ctx, embed, delay=5)


# ---------- Hook into existing bot events ----------
# Patch on_message and on_voice_state_update

_original_on_message = None
_original_on_voice = None

def _patch_events():
    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        if message.author.id in upload_listeners and message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith('image/'):
                future = upload_listeners.pop(message.author.id)
                if not future.done():
                    future.set_result(message)
                return
        await on_message_lvl(message)
        await bot.process_commands(message)

    @bot.event
    async def on_voice_state_update(member, before, after):
        await on_voice_state_lvl(member, before, after)
        await on_voice_state_vc(member, before, after)

_patch_events()


# ---------- Start loops on bot ready ----------
@bot.listen("on_ready")
async def _lvl_on_ready():
    if not lvl_vc_xp_loop.is_running():
        lvl_vc_xp_loop.start()
    if not lvl_expiry_loop.is_running():
        lvl_expiry_loop.start()



# ---------- Run Bot ----------
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not set.")
        exit(1)
    bot.run(TOKEN)
