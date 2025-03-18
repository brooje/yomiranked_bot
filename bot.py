import requests
import discord
import os
import dotenv
import discord.user
import sqlite3
import asyncio
from signal import SIGINT, SIGTERM

from quart import Quart, request


dotenv.load_dotenv()

# Opens a connection to the bot database.
db_conn = sqlite3.connect("bot.db")
db_cursor = db_conn.cursor()

# Create the guild info table if it doesn't exists (allows us to save the match reporting channel)
db_cursor.execute('''CREATE TABLE IF NOT EXISTS guild_data (guild TEXT NOT NULL PRIMARY KEY,
                  report_channel TEXT)''')
db_conn.commit()
db_cursor.close()
db_conn.close()
intents = discord.Intents.default()
intents.members = True

bot = discord.Bot(intents=intents)

ranked_addr = "http://localhost:2221"


# Returns a dictionary representing a rank's information.
def define_rank(name, minElo, maxElo):
    return {"name": name, "minElo": minElo, "maxElo": maxElo}

# Defines the list of ranks.
ranks = [
    define_rank("Earth", None, 500),
    define_rank("Stardust", 500, 700),
    define_rank("Meteor", 700, 900),
    define_rank("Comet", 900, 1100),
    define_rank("Moon", 1100, 1300),
    define_rank("Star", 1300, 1500),
    define_rank("Nebula", 1500, 1700),
    define_rank("Pulsar", 1700, 1900),
    define_rank("Quasar", 1900, 2200),
    define_rank("Nova", 2200, 2500),
    define_rank("Supernova", 2500, None),
]

# Called when the bot starts up.
@bot.event
async def on_ready():
    pass



# Allows a user to connect their steam account to their discord account, using their decimal SteamId64.
@bot.slash_command(
        description="Connect your steam account to your discord account using your key from the ranked mod."
)
async def claimsteam(ctx : discord.ApplicationContext, ingame_key: str):
    hash = ""
    # Get the SteamId hash from the DiscordId; this seems vestigial in its current state, and at this point I'm willing to remove the whole hashing process if possible.
    hash_response = requests.get(ranked_addr + "/gethash", {"id": str(ingame_key)})
    if hash_response.status_code == 400:
        if (hash_response.content == "too long"):
            await ctx.send_response("This Key is too long; are you sure you got it right?", ephemeral = True)
        await ctx.send_response("Your SteamId doesn't seem to have played Starlight Ranked yet.", ephemeral = True)
        return
    elif hash_response.status_code == 200:
        hash = hash_response.json()
    

    # Registers the Discord account that used the command with their Steam hash.
    register_response = requests.post(ranked_addr + "/registerdiscord", json={"steamHash": hash, "discordId": ctx.author.id})
    if register_response.status_code == 400:
        await ctx.send_response("You don't seem to have played Starlight Ranked yet.", ephemeral = True)
        return
    elif register_response.status_code == 200:
        await ctx.send_response("Your Ranked Key is now connected to your Discord!", ephemeral = True)


# Allows a user to manually update their discord rank in a guild based on their ELO.
@bot.slash_command(
        description="Manually update your Discord role from your Starlight rank."
)
async def updaterole(ctx : discord.ApplicationContext):
    discordId = ctx.author.id
    steamId = -1

    # Get the SteamId from the DiscordId.
    disc2steam_response = requests.get(ranked_addr + "/disc2steam", {"discordId": str(discordId)})
    if disc2steam_response.status_code == 400:
        await ctx.send_response("Your Discord account is not connected to any Steam account. Use /claimsteam [ingame key].", ephemeral = True)
        return
    elif disc2steam_response.status_code == 200:
        steamId = disc2steam_response.json()
    else:
        await ctx.send_response("Unknown error.")
    # Get the player's elo from their SteamId.
    elo_response = requests.get(ranked_addr + "/getrank", {"player": str(steamId)})
    if elo_response.status_code == 400:
        await ctx.send_response("Your Discord account is not connected to any Steam account. Use /claimsteam [ingame key]", ephemeral = True)
        return
    elif elo_response.status_code == 200:
        elo = elo_response.json()
        roles = ctx.author.roles
    else:
        await ctx.send_response("Unknown error.")
    
    for rank in ranks:
        # Remove all previous rank roles from the user.
        roles = [role for role in roles if role.name.lower() != rank["name"].lower()] 
        if (elo > (rank["minElo"] or 0)) and (elo <= (rank["maxElo"] or 9999999)):
            # Find and add the user's current rank role.
            matching_roles = [role for role in ctx.author.guild.roles if role.name.lower() == rank["name"].lower()]
            if (len(matching_roles) == 0):   
                await ctx.send_response("The role for the **{}** rank is missing.".format(rank["name"]), ephemeral = True)
                return
            roles.append(matching_roles[0])
            await ctx.send_response("You have been given the **{}** role.".format(rank["name"]), ephemeral = True)

    # Set the users roles to their current roles, minus all rank roles except their current rank role.
    await ctx.author.edit(roles=roles)

def fetch_leaderboard_data():
    leaderboard_response = requests.get(ranked_addr + "/leaderboard")
    if leaderboard_response.status_code == 400:
        return []
    elif leaderboard_response.status_code == 200:
        return leaderboard_response.json()
    
def make_leaderboard_embed(leaderboard_data : list, first_index : int = 0, max_players = 10):
    player_rating_string = ""
    index = first_index
    while (index < first_index + max_players and index < len(leaderboard_data)):
        entry = leaderboard_data[index]
        if (entry["banned"]):
            continue
        player_rating_string += "**{player}**: {rating}\n".format(player = entry["steamName"], elo = entry["rating"])
    return discord.Embed(
                          title="Ranked Leaderboard - {first}-{last}".format(first = first_index, last = first_index + max_players),
                          description=player_rating_string)

# Leaderboard UI view.
class Leaderboard(discord.ui.View): 
    def __init__(self, index = 0):
        super().__init__(timeout=3600, disable_on_timeout=True)

    current_first_index = 0

    @discord.ui.button(label="Previous Page", style=discord.ButtonStyle.primary, emoji="⬅️")
    async def button_callback(self, button, interaction):
        leaderboard_data = fetch_leaderboard_data()
        current_first_index = min(max(current_first_index - 10, 0), len(leaderboard_data) - (len(leaderboard_data) % 10))
        await self.message.edit(view=Leaderboard(timeout=None), embed=make_leaderboard_embed(leaderboard_data, current_first_index))

    @discord.ui.button(label="Next Page", style=discord.ButtonStyle.primary, emoji="➡️")
    async def button_callback(self, button, interaction):
        leaderboard_data = fetch_leaderboard_data()
        current_first_index = min(max(current_first_index + 10, 0), len(leaderboard_data) - (len(leaderboard_data) % 10))
        await self.message.edit(view=Leaderboard(timeout=None), embed=make_leaderboard_embed(leaderboard_data, current_first_index))

# Shows the leaderboard.
@bot.slash_command(
        description = "Shows the leaderboard."
)
async def leaderboard(ctx : discord.ApplicationContext):
    ctx.send_response(view=Leaderboard(), embed=make_leaderboard_embed())


# Allows users with Manage Channels to change the channel match reports go to.
@bot.slash_command(
        description = "Manage Channels Only: Change the channel match reports go to."
)
@discord.commands.permissions.default_permissions(manage_channels=True)
async def setreportchannel(ctx : discord.ApplicationContext):
    channels = [channel for channel in ctx.author.guild.text_channels if str(channel.id) == str(ctx.channel_id)]
    if (len(channels) == 0):
        await ctx.send_response("A channel with this ID doesn't exist.", ephemeral = True)
        return
    db_conn = sqlite3.connect("bot.db")
    db_cursor = db_conn.cursor()
    db_cursor.execute("INSERT OR REPLACE INTO guild_data (guild, report_channel) VALUES (?, ?)", (str(ctx.author.guild.id), str(ctx.channel_id)))
    db_conn.commit()
    db_cursor.close()
    db_conn.close()
    await ctx.send_response("Changed reporting channel to {}".format(channels[0]))

@setreportchannel.error
async def setreportchannel_error(ctx : discord.ApplicationContext, error : discord.ApplicationCommandError):
    print(error)
    await ctx.send_response("Error running command. Do you have the Manage Channels permission?", ephemeral = True)

# Quietly updates a Discord user's role in a guild given their Steam Id, using the Discord Id attached to the Steam Id in the database.
async def sync_ranks(steamId, guild : discord.Guild, elo : int):
    # Get the SteamId from the DiscordId.
    steam2disc_response = requests.get(ranked_addr + "/steam2disc", {"steamId": str(steamId)})
    if steam2disc_response.status_code == 400:
        return
    elif steam2disc_response.status_code == 200:
        discordId = steam2disc_response.json()
    member = guild.get_member(discordId)


    if (member != None):
        roles = member.roles.copy()

        for rank in ranks:
            # Remove all previous rank roles from the user.
            roles = [role for role in roles if role.name.lower() != rank["name"].lower()] 
            if (elo > (rank["minElo"] or 0)) and (elo <= (rank["maxElo"] or 9999999)):
                # Find and add the user's current rank role.
                matching_roles = [role for role in guild.roles if role.name.lower() == rank["name"].lower()]
                if (len(matching_roles) == 0):   
                    return
                roles.append(matching_roles[0])

        # Set the users roles to their current roles, minus all rank roles except their current rank role.
        await member.edit(roles=roles)


app = Quart(__name__)

@app.route("/")
async def index():
    return "<p>Hello, Yomi Ranked!</p>"

@app.route("/reportmatch", methods=['POST'])
async def report_match():
    data = await request.get_json(force=True)
    winnerName = data["winnerName"]
    loserName = data["loserName"]
    winnerEloBefore = data["winnerEloBefore"]
    loserEloBefore = data["loserEloBefore"]
    winnerEloCurrent = data["winnerEloCurrent"]
    loserEloCurrent = data["loserEloCurrent"]
    winnerSteamId = data["winnerSteamId"]
    loserSteamId = data["loserSteamId"]

    winnerDiscordId = -1
    steam2disc_response = requests.get(ranked_addr + "/steam2disc", {"steamId": str(winnerSteamId)})
    if steam2disc_response.status_code == 200:
        winnerDiscordId = steam2disc_response.json()
    else:
        print("Error fetching winner from DB")
        print(steam2disc_response.status_code)

    loserDiscordId = -1
    steam2disc_response = requests.get(ranked_addr + "/steam2disc", {"steamId": str(loserSteamId)})
    if steam2disc_response.status_code == 200:
        loserDiscordId = steam2disc_response.json()
    else:
        print("Error fetching loser from DB")
        print(steam2disc_response.status_code)

    for guild in bot.guilds:
        db_conn = sqlite3.connect("bot.db")
        db_cursor = db_conn.cursor()
        db_cursor.execute("SELECT report_channel FROM guild_data WHERE guild = ?", (str(guild.id),))
        report_match_channel_response = db_cursor.fetchone()
        if (report_match_channel_response == None):
            print("No report channel for guild.")
            db_cursor.close()
            db_conn.close()
            continue
        db_cursor.close()
        db_conn.close()
        report_match_channel = report_match_channel_response[0]
            
        if (winnerDiscordId == "none provided"):
            winnerMention = "unlinked"
        else:
            winnerMember = guild.get_member(int(winnerDiscordId))
            if int(winnerDiscordId) == -1:
                winnerMention = "unlinked"
            else:
                winnerMention = winnerMember.mention
            
    

        if (loserDiscordId == "none provided"):
            loserMention = "unlinked"
        else:
            loserMember = guild.get_member(int(winnerDiscordId))
            if int(loserDiscordId) == -1:
                loserMention = "unlinked"
            else:
                loserMention = loserMember.mention

        await guild.get_channel(int(report_match_channel)).send(embeds=[
            discord.Embed(
                          title="Ranked Match Report - {winner} vs. {loser}".format(winner = winnerName, loser = loserName),
                          description='''**{winner}** defeated **{loser}**!
                          **{winner}** ({winnerMention}) ELO: {winnerEloBefore} → {winnerEloCurrent}
                          **{loser}** ({loserMention}) ELO: {loserEloBefore} → {loserEloCurrent}'''.format(winner = winnerName, winnerEloBefore = winnerEloBefore, winnerEloCurrent = winnerEloCurrent, loser = loserName, loserEloBefore = loserEloBefore, loserEloCurrent = loserEloCurrent, winnerMention = winnerMention, loserMention = loserMention)
                          )
        ], silent=True)
        await sync_ranks(winnerSteamId, guild, winnerEloCurrent)
        await sync_ranks(loserSteamId, guild, loserEloCurrent)
    return "<p>Reported match.</p>", 200


# We gotta do this so both the bot and the endpoints run.
quart_task = bot.loop.create_task(app.run_task(port=8081))

bot.run(os.getenv("TOKEN"))