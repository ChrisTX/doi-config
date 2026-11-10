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

public Plugin myinfo =
{
    name        = "NWI gamedata",
    author      = "DOI revival project",
    description = "Calls and hooks of the game for the other plugins",
    version     = "1.0",
    url         = "https://rev-crew.info"
};

// The file the playlists' data goes through on its way to the editors and back, under SourceMod's
// folder and relative to the game's, which the game's filesystem writes and reads through its
// MOD_WRITE search path: the game folder alone, as MOD has the custom folders first
#define PLAYLIST_FILE "data/nwi_playlist.txt"
#define PLAYLIST_PATH_ID "MOD_WRITE"

GameData g_gamedata;
Handle g_getStep;
Handle g_setStep;
GlobalForward g_onSteamServerDetails;
GlobalForward g_onStatsWorkshopCheck;
// Whether the server is sending its details to Steam, while GetMasterServerPlayerCounts runs for it
bool g_inServerDetails = false;

// The playlists: CPlaylists::UpdateCache, Playlist::GenerateCoalescedData and the KeyValues calls the
// round trip needs (all or none), the Playlist's fields and the editors, each a private forward of its
// own, so that each gets the data at its root
Handle g_updateCache;
Handle g_generateCoalescedData;
Handle g_saveToFile;
Handle g_loadFromFile;
Handle g_clear;
int g_playlistKey;
int g_playlistRuleset;
int g_playlistData;
int g_baseFileSystem;
bool g_playlistsReady = false;
ArrayList g_editors;
char g_playlistFile[PLATFORM_MAX_PATH];
// Whether OnAllPluginsLoaded has run: editors added later rebuild the playlists at once
bool g_allPluginsLoaded = false;

public APLRes AskPluginLoad2(Handle myself, bool late, char[] error, int err_max)
{
    CreateNative("NWI_GetPhysicsTimestep", Native_GetPhysicsTimestep);
    CreateNative("NWI_SetPhysicsTimestep", Native_SetPhysicsTimestep);
    CreateNative("NWI_AddPlaylistEditor", Native_AddPlaylistEditor);
    CreateNative("NWI_RebuildPlaylists", Native_RebuildPlaylists);
    RegPluginLibrary(NWI_GAMEDATA_LIBRARY);
    // Here, as other plugins may add editors before this one's OnPluginStart
    g_editors = new ArrayList();
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

    // The counts the server sends to Steam: the call of GetMasterServerPlayerCounts inside
    // SendUpdatedServerDetails, not those of status or the server's own answers
    if (!Detour("SendUpdatedServerDetails", Detour_ServerDetailsPre, Detour_ServerDetailsPost)
        || !Detour("GetMasterServerPlayerCounts", INVALID_FUNCTION, Detour_PlayerCountsPost))
        LogError("No NWI_OnSteamServerDetails: the gamedata lacks the functions for this platform");

    BuildPath(Path_SM, g_playlistFile, sizeof(g_playlistFile), PLAYLIST_FILE);
    g_playlistsReady = PreparePlaylists();
    if (!g_playlistsReady)
        LogError("No NWI_AddPlaylistEditor: the gamedata lacks the playlists' functions for this platform");

    // Day of Infamy's check of the workshop before it registers the server for its stats
    g_onStatsWorkshopCheck = new GlobalForward("NWI_OnStatsWorkshopCheck", ET_Ignore, Param_CellByRef);
    if (NWI_GetGame() == NWIGame_DoI
        && !Detour("CServerUGCManager::IsEnabled", INVALID_FUNCTION, Detour_WorkshopEnabledPost))
        LogError("No NWI_OnStatsWorkshopCheck: the gamedata lacks the function for this platform");
}

public void OnAllPluginsLoaded()
{
    g_allPluginsLoaded = true;
    // The game read the playlists before SourceMod was there: once more, now with the editors
    if (g_editors.Length > 0)
        RebuildPlaylists();
}

// The calls, fields and detour of the playlists; false if the gamedata lacks any of them
bool PreparePlaylists()
{
    g_playlistKey = g_gamedata.GetOffset("Playlist::m_key");
    g_playlistRuleset = g_gamedata.GetOffset("Playlist::m_ruleset");
    g_playlistData = g_gamedata.GetOffset("Playlist::m_data");
    g_baseFileSystem = g_gamedata.GetOffset("IFileSystem::IBaseFileSystem");
    if (g_playlistKey == -1 || g_playlistRuleset == -1 || g_playlistData == -1 || g_baseFileSystem == -1)
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
    // bool KeyValues::SaveToFile(IBaseFileSystem *, const char *file, const char *pathID, bool)
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "KeyValues::SaveToFile"))
        return false;
    PrepSDKCall_SetReturnInfo(SDKType_Bool, SDKPass_Plain);
    PrepSDKCall_AddParameter(SDKType_PlainOldData, SDKPass_Plain);
    PrepSDKCall_AddParameter(SDKType_String, SDKPass_Pointer);
    PrepSDKCall_AddParameter(SDKType_String, SDKPass_Pointer);
    PrepSDKCall_AddParameter(SDKType_Bool, SDKPass_Plain);
    g_saveToFile = EndPrepSDKCall();
    // bool KeyValues::LoadFromFile(IBaseFileSystem *, const char *file, const char *pathID,
    //     GetSymbolProc_t evaluateSymbol), without a function for the conditions ([$WIN32])
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "KeyValues::LoadFromFile"))
        return false;
    PrepSDKCall_SetReturnInfo(SDKType_Bool, SDKPass_Plain);
    PrepSDKCall_AddParameter(SDKType_PlainOldData, SDKPass_Plain);
    PrepSDKCall_AddParameter(SDKType_String, SDKPass_Pointer);
    PrepSDKCall_AddParameter(SDKType_String, SDKPass_Pointer);
    PrepSDKCall_AddParameter(SDKType_PlainOldData, SDKPass_Plain);
    g_loadFromFile = EndPrepSDKCall();
    // void KeyValues::Clear(): its keys, its value
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Signature, "KeyValues::Clear"))
        return false;
    g_clear = EndPrepSDKCall();

    return g_gamedata.GetAddress("g_Playlists") != Address_Null
        && Detour("Playlist::SetData", INVALID_FUNCTION, Detour_PlaylistSetDataPost);
}

// Has the game read its playlists anew, which goes through the editors: the playlists stay as the
// game made them until the next rebuild, e.g. after an editor is gone
void RebuildPlaylists()
{
    if (!g_playlistsReady)
        return;
    SDKCall(g_updateCache, g_gamedata.GetAddress("g_Playlists"));
}

// After Playlist::SetData, which copied the file's data to the Playlist and merged the ruleset's blocks:
// the editors change the Playlist's own copy, then the merge runs again. The game's copies of a
// Playlist for its matchmaking come from that copy, already edited. The data goes to the editors
// through a file, as the game's KeyValues aren't SourceMod's.
MRESReturn Detour_PlaylistSetDataPost(Address playlist)
{
    // Editors whose plugin is gone have no function left
    for (int i = g_editors.Length - 1; i >= 0; i--)
    {
        PrivateForward editor = g_editors.Get(i);
        if (editor.FunctionCount == 0)
        {
            delete editor;
            g_editors.Erase(i);
        }
    }
    if (g_editors.Length == 0)
        return MRES_Ignored;

    char key[260], ruleset[64];
    LoadString(playlist + view_as<Address>(g_playlistKey), key, sizeof(key));
    LoadString(playlist + view_as<Address>(g_playlistRuleset), ruleset, sizeof(ruleset));
    Address data = LoadFromAddress(playlist + view_as<Address>(g_playlistData), NumberType_Int32);
    Address fileSystem = g_gamedata.GetAddress("g_pFullFileSystem");
    if (data == Address_Null || fileSystem == Address_Null)
        return MRES_Ignored;
    fileSystem += view_as<Address>(g_baseFileSystem);

    if (!SDKCall(g_saveToFile, data, fileSystem, g_playlistFile, PLAYLIST_PATH_ID, false))
    {
        LogError("Can't save the data of playlist %s (%s) to %s", key, ruleset, g_playlistFile);
        return MRES_Ignored;
    }
    KeyValues kv = new KeyValues("playlist");
    if (!kv.ImportFromFile(g_playlistFile))
    {
        LogError("Can't read the data of playlist %s (%s) from %s", key, ruleset, g_playlistFile);
        delete kv;
        DeleteFile(g_playlistFile);
        return MRES_Ignored;
    }

    bool changed = false;
    for (int i = 0; i < g_editors.Length; i++)
    {
        Action result = Plugin_Continue;
        kv.Rewind();
        Call_StartForward(g_editors.Get(i));
        Call_PushString(key);
        Call_PushString(ruleset);
        Call_PushCell(kv);
        if (Call_Finish(result) == SP_ERROR_NONE && result == Plugin_Changed)
            changed = true;
    }

    if (changed)
    {
        kv.Rewind();
        if (kv.ExportToFile(g_playlistFile))
        {
            // Into the same KeyValues, which the Playlist owns
            SDKCall(g_clear, data);
            if (SDKCall(g_loadFromFile, data, fileSystem, g_playlistFile, PLAYLIST_PATH_ID, 0))
                SDKCall(g_generateCoalescedData, playlist);
            else
                LogError("Can't load the edited data of playlist %s (%s): it's empty now", key, ruleset);
        }
        else
            LogError("Can't save the edited data of playlist %s (%s) to %s", key, ruleset, g_playlistFile);
    }
    delete kv;
    DeleteFile(g_playlistFile);
    return MRES_Ignored;
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

public any Native_AddPlaylistEditor(Handle plugin, int numParams)
{
    if (!g_playlistsReady)
        return false;
    PrivateForward editor = new PrivateForward(ET_Hook, Param_String, Param_String, Param_Cell);
    editor.AddFunction(plugin, GetNativeFunction(1));
    g_editors.Push(editor);
    // At the server's start, OnAllPluginsLoaded rebuilds them once for all editors
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
        counts[i] = params.Get(i + 1);
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

// The physics environment, which the game creates anew at every map start
Address PhysicsEnvironment()
{
    return g_gamedata.GetAddress("physenv");
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
