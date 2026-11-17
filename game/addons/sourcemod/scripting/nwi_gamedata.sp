// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Calls and hooks of the game for the other plugins of doi-config, in Day of Infamy and Insurgency: the
// only plugin with gamedata (gamedata/nwi.games.txt), whose functions it offers as the natives and
// forwards of nwi_gamedata.inc. What the gamedata lacks on a platform is logged and left out; the rest
// works.

#include <sourcemod>
#include <sdktools>
#include <dhooks>
#include <nwi>
#define NWI_GAMEDATA_PROVIDER
#include <nwi_gamedata>

#pragma semicolon 1
#pragma newdecls required

// SourceMod 1.13's 64-bit Address, LoadAddressFromAddress and SDKType_Address: built with 1.12, an
// Address is a 32-bit cell, and the globals of 64-bit Windows stay out of reach (see GameGlobal)
#if SOURCEMOD_V_MAJOR > 1 || SOURCEMOD_V_MINOR >= 13
#define NWI_INT64_ADDRESS
#define SDKType_Pointer SDKType_Address
#else
#define SDKType_Pointer SDKType_PlainOldData
#endif

public Plugin myinfo =
{
    name        = "NWI gamedata",
    author      = "DOI revival project",
    description = "Calls and hooks of the game for the other plugins",
    version     = "1.0",
    url         = "https://rev-crew.info"
};

// The search path the game's filesystem reads the playlists' replacements through, relative to the
// game folder
#define PLAYLIST_PATH_ID "MOD"

GameData g_gamedata;
Handle g_getStep;
Handle g_setStep;
GlobalForward g_onSteamServerDetails;
GlobalForward g_onStatsWorkshopCheck;
// Whether the server is sending its details to Steam, while GetMasterServerPlayerCounts runs for it
bool g_inServerDetails = false;
// The game rules' state the game starts with, after the pregame state (GameRulesState_t)
#define GAME_STATE_STARTGAME 2

// Rounds with bots only: the game doesn't wait for human players while bots are on the playing teams;
// CINSRules::State_Transition, which starts the game from the pregame state, and
// CINSRules::GetTotalActivePlayersOnTeam, a team's players with its bots
ConVar g_botOnlyRounds;
Handle g_stateTransition;
Handle g_activePlayersOnTeam;

// The playlists: CPlaylists::UpdateCache, Playlist::GenerateCoalescedData and the KeyValues calls that
// load a replacement (all or none), the Playlist's fields, and the folder of the replacements (none
// while empty)
Handle g_updateCache;
Handle g_generateCoalescedData;
Handle g_loadFromFile;
Handle g_clear;
int g_playlistKey;
int g_playlistData;
int g_baseFileSystem;
bool g_playlistsReady = false;
char g_replacements[PLATFORM_MAX_PATH];
// Whether OnAllPluginsLoaded has run: a folder set later rebuilds the playlists at once
bool g_allPluginsLoaded = false;

public APLRes AskPluginLoad2(Handle myself, bool late, char[] error, int err_max)
{
    CreateNative("NWI_GetPhysicsTimestep", Native_GetPhysicsTimestep);
    CreateNative("NWI_SetPhysicsTimestep", Native_SetPhysicsTimestep);
    CreateNative("NWI_ReplacePlaylists", Native_ReplacePlaylists);
    CreateNative("NWI_RebuildPlaylists", Native_RebuildPlaylists);
    RegPluginLibrary(NWI_GAMEDATA_LIBRARY);
    g_allPluginsLoaded = late;
    return APLRes_Success;
}

public void OnPluginStart()
{
    NWI_RequireGame();
    g_gamedata = new GameData("nwi.games");
    if (g_gamedata == null)
        SetFailState("Can't load gamedata/nwi.games.txt");
    g_onSteamServerDetails = new GlobalForward("NWI_OnSteamServerDetails", ET_Ignore, Param_CellByRef,
        Param_CellByRef, Param_CellByRef);

    // IPhysicsEnvironment::GetSimulationTimestep and SetSimulationTimestep
    StartPrepSDKCall(SDKCall_Raw);
    if (PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Virtual, "GetSimulationTimestep"))
    {
        PrepSDKCall_SetReturnInfo(SDKType_Float, SDKPass_Plain);
        g_getStep = EndPrepSDKCall();
    }
    StartPrepSDKCall(SDKCall_Raw);
    if (PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Virtual, "SetSimulationTimestep"))
    {
        PrepSDKCall_AddParameter(SDKType_Float, SDKPass_Plain);
        g_setStep = EndPrepSDKCall();
    }
    if (g_getStep == null || g_setStep == null)
        LogError("No physics timestep calls: the gamedata lacks their offsets");
#if !defined NWI_INT64_ADDRESS
    // 64-bit Windows, the only platform whose gamedata has physenv::rip: physenv takes SourceMod
    // 1.13's includes and compiler, see GameGlobal. At 64 tick or below, nothing needs the physics
    // step.
    if (g_gamedata.GetOffset("physenv::rip") != -1 && GetTickInterval() < 0.015625)
        LogError("The physics step stays the tick's at %.0f tick, grenades bounce more than at 64: on 64-bit Windows, nwi_gamedata needs to be compiled with SourceMod 1.13, not %s",
            1.0 / GetTickInterval(), SOURCEMOD_VERSION);
#endif

    // The counts the server sends to Steam: the call of GetMasterServerPlayerCounts inside
    // SendUpdatedServerDetails, not those of status or the server's own answers
    if (!Detour("SendUpdatedServerDetails", Detour_ServerDetailsPre, Detour_ServerDetailsPost)
        || !Detour("GetMasterServerPlayerCounts", INVALID_FUNCTION, Detour_PlayerCountsPost))
        LogError("No NWI_OnSteamServerDetails: the gamedata lacks the functions for this platform");

    g_playlistsReady = PreparePlaylists();
    if (!g_playlistsReady)
        LogError("No NWI_ReplacePlaylists: the gamedata lacks the playlists' functions for this platform%s",
            g_gamedata.GetOffset("g_Playlists::rip") != -1 ? ", on 64-bit Windows nwi_gamedata needs to be compiled with SourceMod 1.13" : "");

    // The game waits for human players before it starts a round, also with bots on the teams: with
    // nwi_bot_only_rounds, it doesn't while there are bots, e.g. for a casual server that bots keep
    // going until players join, and the integration tests' rounds
    g_botOnlyRounds = CreateConVar("nwi_bot_only_rounds", "0",
        "1: start rounds without human players while bots are on the playing teams, which the game waits for otherwise",
        _, true, 0.0, true, 1.0);
    StartPrepSDKCall(SDKCall_Raw);
    if (PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "CINSRules::State_Transition"))
    {
        PrepSDKCall_AddParameter(SDKType_PlainOldData, SDKPass_Plain);
        g_stateTransition = EndPrepSDKCall();
    }
    StartPrepSDKCall(SDKCall_Raw);
    if (PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "CINSRules::GetTotalActivePlayersOnTeam"))
    {
        PrepSDKCall_AddParameter(SDKType_PlainOldData, SDKPass_Plain);
        PrepSDKCall_SetReturnInfo(SDKType_PlainOldData, SDKPass_Plain);
        g_activePlayersOnTeam = EndPrepSDKCall();
    }
    if (g_stateTransition == null || g_activePlayersOnTeam == null
        || !Detour("CINSRules::ShouldBeWaitingForPlayers", INVALID_FUNCTION, Detour_WaitingForPlayersPost)
        || !Detour("CINSRules::State_Think_PREGAME", Detour_PregamePre, INVALID_FUNCTION)
        || !Detour("CINSRules::GetTotalActiveHumanPlayersOnTeam", INVALID_FUNCTION, Detour_ActiveHumansPost))
        LogError("No nwi_bot_only_rounds: the gamedata lacks the functions for this platform");

    // Day of Infamy's check of the workshop before it registers the server for its stats
    g_onStatsWorkshopCheck = new GlobalForward("NWI_OnStatsWorkshopCheck", ET_Ignore, Param_CellByRef);
    if (NWI_GetGame() == NWIGame_DoI
        && !Detour("CServerUGCManager::IsEnabled", INVALID_FUNCTION, Detour_WorkshopEnabledPost))
        LogError("No NWI_OnStatsWorkshopCheck: the gamedata lacks the function for this platform");
}

public void OnAllPluginsLoaded()
{
    g_allPluginsLoaded = true;
    // The game read the playlists before SourceMod was there: once more, now with the replacements
    if (g_replacements[0] != '\0')
        RebuildPlaylists();
}

// The calls, fields and detour of the playlists; false if the gamedata lacks any of them
bool PreparePlaylists()
{
    g_playlistKey = g_gamedata.GetOffset("Playlist::m_key");
    g_playlistData = g_gamedata.GetOffset("Playlist::m_data");
    g_baseFileSystem = g_gamedata.GetOffset("IFileSystem::IBaseFileSystem");
    if (g_playlistKey == -1 || g_playlistData == -1 || g_baseFileSystem == -1)
        return false;

    // void CPlaylists::UpdateCache()
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "CPlaylists::UpdateCache"))
        return false;
    g_updateCache = EndPrepSDKCall();
    // void Playlist::GenerateCoalescedData()
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "Playlist::GenerateCoalescedData"))
        return false;
    g_generateCoalescedData = EndPrepSDKCall();
    // bool KeyValues::LoadFromFile(IBaseFileSystem *, const char *file, const char *pathID,
    //     GetSymbolProc_t evaluateSymbol), without a function for the conditions ([$WIN32])
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "KeyValues::LoadFromFile"))
        return false;
    PrepSDKCall_SetReturnInfo(SDKType_Bool, SDKPass_Plain);
    PrepSDKCall_AddParameter(SDKType_Pointer, SDKPass_Plain);
    PrepSDKCall_AddParameter(SDKType_String, SDKPass_Pointer);
    PrepSDKCall_AddParameter(SDKType_String, SDKPass_Pointer);
    PrepSDKCall_AddParameter(SDKType_Pointer, SDKPass_Plain, VDECODE_FLAG_ALLOWNULL);
    g_loadFromFile = EndPrepSDKCall();
    // void KeyValues::Clear(): its keys, its value
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "KeyValues::Clear"))
        return false;
    g_clear = EndPrepSDKCall();

    // Linux: after Playlist::SetData. Windows has no SetData of its own, MSVC inlined it into
    // CPlaylists::GeneratePlaylist: before each Playlist::GenerateCoalescedData instead
    return GameGlobal("g_Playlists", false) != Address_Null
        && (Detour("Playlist::SetData", INVALID_FUNCTION, Detour_PlaylistSetDataPost)
            || Detour("Playlist::GenerateCoalescedData", Detour_GenerateCoalescedDataPre, INVALID_FUNCTION));
}

// Has the game make its playlists anew from their files, with the replacements
void RebuildPlaylists()
{
    if (!g_playlistsReady)
        return;
    SDKCall(g_updateCache, GameGlobal("g_Playlists", false));
}

// After Playlist::SetData, which copied the playlist file's data to the Playlist and merged the
// ruleset's blocks: if the folder of the replacements has one for the playlist (<folder>/<key>.playlist),
// it replaces the Playlist's own copy, and the merge runs again. The game's copies of a Playlist for its
// matchmaking come from that copy. The checksum of the playlist stays that of the game's file, which
// the game took before.
MRESReturn Detour_PlaylistSetDataPost(Address playlist)
{
    if (ReplacePlaylistData(playlist))
        SDKCall(g_generateCoalescedData, playlist);
    return MRES_Ignored;
}

// Windows: before Playlist::GenerateCoalescedData, which GeneratePlaylist calls after its inlined
// SetData and again after the ruleset, and the matchmaking for its copies of a Playlist. The merge
// that follows reads the replacement, which is loaded anew each time, to the same result.
MRESReturn Detour_GenerateCoalescedDataPre(Address playlist)
{
    ReplacePlaylistData(playlist);
    return MRES_Ignored;
}

// Loads the playlist's replacement into the Playlist's own data, if the folder has one; true if it
// did
bool ReplacePlaylistData(Address playlist)
{
    if (g_replacements[0] == '\0')
        return false;
    char key[260], path[PLATFORM_MAX_PATH];
    LoadString(playlist + view_as<Address>(g_playlistKey), key, sizeof(key));
    FormatEx(path, sizeof(path), "%s/%s.playlist", g_replacements, key);
    if (!FileExists(path, true, PLAYLIST_PATH_ID))
        return false;
    Address data = LoadPointer(playlist + view_as<Address>(g_playlistData));
    Address fileSystem = GameGlobal("g_pFullFileSystem", true);
    if (data == Address_Null || fileSystem == Address_Null)
        return false;
    fileSystem += view_as<Address>(g_baseFileSystem);
    // Into the same KeyValues, which the Playlist owns
    SDKCall(g_clear, data);
    if (SDKCall(g_loadFromFile, data, fileSystem, path, PLAYLIST_PATH_ID, Address_Null))
        return true;
    LogError("Can't load %s: playlist %s is empty now", path, key);
    return false;
}

// A pointer in the game's memory
Address LoadPointer(Address address)
{
#if defined NWI_INT64_ADDRESS
    return LoadAddressFromAddress(address);
#else
    return LoadFromAddress(address, NumberType_Int32);
#endif
}

// A global of the game, from the gamedata's Addresses: the object, or with pointer the pointer stored
// there. On 64-bit Windows, the game's code reaches globals relative to the instruction (RIP), which
// Addresses can't follow: the int32 at <name>::rip of the signature <name> is the global's distance
// from <name>::rip_next. Only that platform's gamedata has those offsets, and only SourceMod 1.13 has
// 64-bit Addresses.
Address GameGlobal(const char[] name, bool pointer)
{
#if defined NWI_INT64_ADDRESS
    char key[64];
    FormatEx(key, sizeof(key), "%s::rip", name);
    int displacement = g_gamedata.GetOffset(key);
    StrCat(key, sizeof(key), "_next");
    int next = g_gamedata.GetOffset(key);
    if (displacement != -1 && next != -1)
    {
        Address instruction = g_gamedata.GetMemSig(name);
        if (instruction == Address_Null)
            return Address_Null;
        int distance = LoadFromAddress(instruction + view_as<Address>(displacement), NumberType_Int32);
        Address global = instruction + view_as<Address>(next) + view_as<Address>(distance);
        return pointer ? LoadAddressFromAddress(global) : global;
    }
#else
    // The Addresses read the pointer themselves
    #pragma unused pointer
#endif
    return g_gamedata.GetAddress(name);
}

// A string of the game's memory, cut at the buffer's end
void LoadString(Address address, char[] buffer, int maxlength)
{
    int i = 0;
    for (; i < maxlength - 1; i++)
    {
        buffer[i] = LoadFromAddress(address + view_as<Address>(i), NumberType_Int8);
        if (buffer[i] == '\0')
            return;
    }
    buffer[i] = '\0';
}

// After CServerUGCManager::IsEnabled, which only CDOIPersistence::RegisterServer asks: it doesn't
// register a server that uses the workshop for the game's stats
MRESReturn Detour_WorkshopEnabledPost(DHookReturn result)
{
    bool workshop = result.Value;
    bool original = workshop;
    Call_StartForward(g_onStatsWorkshopCheck);
    Call_PushCellRef(workshop);
    Call_Finish();
    if (workshop == original)
        return MRES_Ignored;
    result.Value = workshop;
    return MRES_Override;
}

public any Native_ReplacePlaylists(Handle plugin, int numParams)
{
    if (!g_playlistsReady)
        return false;
    GetNativeString(1, g_replacements, sizeof(g_replacements));
    // At the server's start, OnAllPluginsLoaded rebuilds them
    if (g_allPluginsLoaded)
        RebuildPlaylists();
    return true;
}

public any Native_RebuildPlaylists(Handle plugin, int numParams)
{
    if (!g_playlistsReady)
        return false;
    RebuildPlaylists();
    return true;
}

// Enables a detour of the gamedata's Functions; false if it isn't there
bool Detour(const char[] name, DHookCallback pre, DHookCallback post)
{
    DynamicDetour detour = DynamicDetour.FromConf(g_gamedata, name);
    if (detour == null)
        return false;
    bool enabled = true;
    if (pre != INVALID_FUNCTION)
        enabled = detour.Enable(Hook_Pre, pre);
    if (post != INVALID_FUNCTION)
        enabled = enabled && detour.Enable(Hook_Post, post);
    return enabled;
}

MRESReturn Detour_ServerDetailsPre()
{
    g_inServerDetails = true;
    return MRES_Ignored;
}

MRESReturn Detour_ServerDetailsPost()
{
    g_inServerDetails = false;
    return MRES_Ignored;
}

// The three counts are pointers (int &): read, passed to the forward, written back
MRESReturn Detour_PlayerCountsPost(DHookParam params)
{
    if (!g_inServerDetails)
        return MRES_Ignored;
    Address counts[3];
    int values[3];
    for (int i = 0; i < 3; i++)
    {
        // The whole pointer: Get returns a cell, half of a 64-bit one
        counts[i] = params.GetAddress(i + 1);
        values[i] = LoadFromAddress(counts[i], NumberType_Int32);
    }
    int humans = values[0], maximum = values[1], bots = values[2];
    Call_StartForward(g_onSteamServerDetails);
    Call_PushCellRef(humans);
    Call_PushCellRef(maximum);
    Call_PushCellRef(bots);
    Call_Finish();
    int changed[3];
    changed[0] = humans;
    changed[1] = maximum;
    changed[2] = bots;
    for (int i = 0; i < 3; i++)
    {
        if (changed[i] != values[i])
            StoreToAddress(counts[i], changed[i], NumberType_Int32);
    }
    return MRES_Ignored;
}

// After CINSRules::ShouldBeWaitingForPlayers: with nwi_bot_only_rounds, bots on the playing teams end
// the waiting as players do
MRESReturn Detour_WaitingForPlayersPost(DHookReturn result)
{
    if (!g_botOnlyRounds.BoolValue || !result.Value || !BotsPlaying())
        return MRES_Ignored;
    result.Value = false;
    return MRES_Override;
}

// Before CINSRules::State_Think_PREGAME: a dedicated server stays in the pregame state until a human
// player is on it, whatever ShouldBeWaitingForPlayers says. With nwi_bot_only_rounds, bots and no human
// players, the game starts (state 2) as it would with them.
MRESReturn Detour_PregamePre(Address rules)
{
    if (!g_botOnlyRounds.BoolValue || !BotsPlaying() || HumansConnected())
        return MRES_Ignored;
    SDKCall(g_stateTransition, rules, GAME_STATE_STARTGAME);
    return MRES_Supercede;
}

// After CINSRules::GetTotalActiveHumanPlayersOnTeam: the coop modes lose a round without human players
// on the players' team. With nwi_bot_only_rounds and no human players, a team's bots count as its
// humans, here and wherever else the game counts the active humans, e.g. for the capture speed.
MRESReturn Detour_ActiveHumansPost(Address rules, DHookReturn result, DHookParam params)
{
    if (!g_botOnlyRounds.BoolValue || HumansConnected())
        return MRES_Ignored;
    result.Value = SDKCall(g_activePlayersOnTeam, rules, params.Get(1));
    return MRES_Override;
}

// Whether a bot is on one of the playing teams (2 and 3), not SourceTV's
bool BotsPlaying()
{
    for (int client = 1; client <= MaxClients; client++)
    {
        if (IsClientInGame(client) && IsFakeClient(client) && !IsClientSourceTV(client)
            && GetClientTeam(client) >= 2)
            return true;
    }
    return false;
}

// Whether a human player is connected, also one still loading
bool HumansConnected()
{
    for (int client = 1; client <= MaxClients; client++)
    {
        if (IsClientConnected(client) && !IsFakeClient(client))
            return true;
    }
    return false;
}

// The physics environment, which the game creates anew at every map start
Address PhysicsEnvironment()
{
    return GameGlobal("physenv", true);
}

public any Native_GetPhysicsTimestep(Handle plugin, int numParams)
{
    Address env = PhysicsEnvironment();
    if (env == Address_Null || g_getStep == null)
        return false;
    SetNativeCellRef(1, SDKCall(g_getStep, env));
    return true;
}

public any Native_SetPhysicsTimestep(Handle plugin, int numParams)
{
    Address env = PhysicsEnvironment();
    if (env == Address_Null || g_setStep == null)
        return false;
    SDKCall(g_setStep, env, view_as<float>(GetNativeCell(1)));
    return true;
}
