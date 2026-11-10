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

GameData g_gamedata;
Handle g_getStep;
Handle g_setStep;
GlobalForward g_onSteamServerDetails;
// Whether the server is sending its details to Steam, while GetMasterServerPlayerCounts runs for it
bool g_inServerDetails = false;

public APLRes AskPluginLoad2(Handle myself, bool late, char[] error, int err_max)
{
    CreateNative("NWI_GetPhysicsTimestep", Native_GetPhysicsTimestep);
    CreateNative("NWI_SetPhysicsTimestep", Native_SetPhysicsTimestep);
    RegPluginLibrary(NWI_GAMEDATA_LIBRARY);
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
