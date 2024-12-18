import requests
import discord
import os
import dotenv
import discord.user
import sqlite3
import asyncio

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

bot = discord.Bot()

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

# Allows a user to connect their steam account to their discord account, using their decimal SteamID64.
@bot.slash_command(
        description="Connect your steam account to your discord account."
)
async def claimsteam(ctx : discord.ApplicationContext, steamid64: str):
    hash = ""
    # Get the SteamID hash from the DiscordID; this seems vestigial in its current state, and at this point I'm willing to remove the whole hashing process if possible.
    hash_response = requests.get(ranked_addr + "/gethash", {"id": str(steamid64)})
    if hash_response.status_code == 400:
        if (hash_response.content == "too long"):
            await ctx.send_response("This SteamID is too long; are you sure you got it right?", ephemeral = True)
        await ctx.send_response("Your SteamID doesn't seem to have played Ranked yet.", ephemeral = True)
        return
    elif hash_response.status_code == 200:
        hash = hash_response.json()
    

    # Registers the Discord account that used the command with their Steam hash.
    register_response = requests.post(ranked_addr + "/registerdiscord", json={"steamHash": hash, "discordId": ctx.author.id})
    if register_response.status_code == 400:
        await ctx.send_response("Your SteamID doesn't seem to have played Ranked yet.", ephemeral = True)
        return
    elif register_response.status_code == 200:
        await ctx.send_response("Your SteamID is now connected to your Discord!", ephemeral = True)


# Allows a user to manually update their discord rank in a guild based on their ELO.
@bot.slash_command(
        description="Manually update your Discord role from your Starlight rank."
)
async def updaterole(ctx : discord.ApplicationContext):
    discordID = ctx.author.id
    steamID = -1

    # Get the SteamID from the DiscordID.
    disc2steam_response = requests.get(ranked_addr + "/disc2steam", {"discordId": str(discordID)})
    if disc2steam_response.status_code == 400:
        await ctx.send_response("Your Discord account is not connected to any Steam account. Use /registersteam [steamID].", ephemeral = True)
        return
    elif disc2steam_response.status_code == 200:
        steamID = disc2steam_response.json()
    else:
        await ctx.send_response("Unknown error.")
    # Get the player's elo from their SteamID.
    elo_response = requests.get(ranked_addr + "/getrank", {"player": str(steamID)})
    if elo_response.status_code == 400:
        await ctx.send_response("Your Discord account is not connected to any Steam account. Use /registersteam [steamID].", ephemeral = True)
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
    
# Allows users with Manage Channels to change the channel match reports go to.
@bot.slash_command(
        description = "Manage Channels Only: Change the channel match reports go to."
)
@discord.commands.permissions.default_permissions(manage_channels=True)
async def setreportchannel(ctx : discord.ApplicationContext, channelid : str):
    db_conn = sqlite3.connect("bot.db")
    db_cursor = db_conn.cursor()
    db_cursor.execute("INSERT INTO guild_data (guild, report_channel) VALUES (?, ?)", (str(ctx.author.guild.id), channelid))
    db_conn.commit()
    db_cursor.close()
    db_conn.close()
    channels = [channel for channel in ctx.author.guild.text_channels if channel.id == int(channelid)]
    if (len(channels) == 0):
        await ctx.send_response("A channel with this ID doesn't exist.", ephemeral = True)
    await ctx.send_response("Changed reporting channel to {}".format(channels[0]))

@setreportchannel.error
async def setreportchannel_error(ctx : discord.ApplicationContext, channelid : str):
    await ctx.send_response("You don't have the Manage Channels permission.", ephemeral = True)

# Quietly updates a Discord user's role in a guild given their Steam ID, using the Discord ID attached to the Steam ID in the database.
async def sync_ranks(steamID, guild : discord.Guild, elo : int):
    # Get the SteamID from the DiscordID.
    steam2disc_response = requests.get(ranked_addr + "/steam2disc", {"steamId": str(steamID)})
    if steam2disc_response.status_code == 400:
        return
    elif steam2disc_response.status_code == 200:
        discordID = steam2disc_response.json()
    member = guild.get_member(discordID)


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

    steam2disc_response = requests.get(ranked_addr + "/steam2disc", {"steamId": str(winnerSteamId)})
    if steam2disc_response.status_code == 400:
        return
    elif steam2disc_response.status_code == 200:
        winnerDiscordID = steam2disc_response.json()

    steam2disc_response = requests.get(ranked_addr + "/steam2disc", {"steamId": str(loserSteamId)})
    if steam2disc_response.status_code == 400:
        return
    elif steam2disc_response.status_code == 200:
        loserDiscordID = steam2disc_response.json()

    for guild in bot.guilds:
        db_conn = sqlite3.connect("bot.db")
        db_cursor = db_conn.cursor()
        db_cursor.execute("SELECT report_channel FROM guild_data WHERE guild = ?", (str(guild.id),))
        report_match_channel_query = db_cursor.fetchone()
        if (report_match_channel_query == None):
            continue
        db_cursor.close()
        db_conn.close()
        report_match_channel = report_match_channel_query[0]
            
      
        winnerMention = guild.get_member(winnerDiscordID).mention
        loserMention = guild.get_member(loserDiscordID).mention



        await guild.get_channel(int(report_match_channel)).send(embeds=[
            discord.Embed(
                          title="Ranked Match Report - {winner} vs. {loser}".format(winner = winnerName, loser = loserName),
                          description='''**{winner}** defeated **{loser}**!
                          **{winner}** ({winnerMention}) ELO: {winnerEloBefore} → {winnerEloCurrent}
                          **{loser}** ({loserMention}) ELO: {loserEloBefore} → {loserEloCurrent}'''.format(winner = winnerName, winnerEloBefore = winnerEloBefore, winnerEloCurrent = winnerEloCurrent, loser = loserName, loserEloBefore = loserEloBefore, loserEloCurrent = loserEloCurrent, winnerMention = winnerMention, loserMention = loserMention)
                          )
        ], silent=True)
        sync_ranks(winnerSteamId, guild, winnerEloCurrent)
        sync_ranks(loserSteamId, guild, loserEloCurrent)
    return "<p>Reported match.</p>", 200



bot.loop.create_task(app.run_task(port=8081))

bot.run(os.getenv("TOKEN"))