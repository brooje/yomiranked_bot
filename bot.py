import requests
import discord
import os
import dotenv
import discord.user
from flask import Flask, request


dotenv.load_dotenv()

bot = discord.Bot()

ranked_addr = "http://150.136.44.240:2221"


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
        print(hash_response.content)
        await ctx.send_response("Your SteamID doesn't seem to have played Ranked yet.", ephemeral = True)
        return
    elif hash_response.status_code == 200:
        hash = hash_response.json()
    

    # Registers the Discord account that used the command with their Steam hash.
    register_response = requests.post(ranked_addr + "/registerdiscord", json={"steamHash": hash, "discordId": ctx.author.id})
    if register_response.status_code == 400:
        print(register_response.content)
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
    # Get the player's elo from their SteamID.
    elo_response = requests.get(ranked_addr + "/getrank", {"player": str(steamID)})
    if elo_response.status_code == 400:
        await ctx.send_response("Your Discord account is not connected to any Steam account. Use /registersteam [steamID].", ephemeral = True)
        return
    elif elo_response.status_code == 200:
        elo = elo_response.json()
        roles = ctx.author.roles

    
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
    
    

# Quietly updates a Discord user's role in a guild given their Steam ID, using the Discord ID attached to the Steam ID in the database.
async def sync_ranks(steamID, guild : discord.Guild):
    # Get the SteamID from the DiscordID.
    steam2disc_response = requests.get(ranked_addr + "/steam2disc", {"steamId": str(steamID)})
    if steam2disc_response.status_code == 400:
        return
    elif steam2disc_response.status_code == 200:
        discordID = steam2disc_response.json()
    member = guild.get_member(discordID)

    elo_response = requests.get(ranked_addr + "/getrank", {"player": str(steamID)})
    if elo_response.status_code == 400:
        print("Error fetching user's rank.")
        return
    elif elo_response.status_code == 200:
        elo = elo_response.json()



    if (member != None):
        roles = member.roles

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



bot.run(str(os.getenv("TOKEN")))


app = Flask(__name__)

@app.route("/")
def index():
    return "<p>Hello, Yomi Ranked!</p>"

@app.route("/updateranks", methods=['POST'])
def report_match():
    data = request.get_json(force=True)
    winnerSteamId = data["winnerSteamId"]
    loserSteamId = data["loserSteamId"]
    if (type(winnerSteamId) != str or type(loserSteamId) != str):
        return
    idsToUpdate = [winnerSteamId, loserSteamId]
    for guild in bot.guilds:
        for id in idsToUpdate:
            sync_ranks(id, guild)

app.run(port=8080)