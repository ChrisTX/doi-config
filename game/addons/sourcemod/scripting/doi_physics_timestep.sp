// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Keeps the step of the physics simulation (VPhysics) at 1/64 s when the server runs at a higher
// tickrate, so that physics objects behave as they do at the game's 64 tick.
//
// At every map start, the game sets the physics step to the tick's interval (CPhysicsHook::
// LevelInitPreEntity: interval / (floor(interval * 63) + 1)), so at 128 tick the physics runs at
// 1/128 s. Grenades, which are physics objects, then bounce a lot more: their contacts were made for
// the step of 64 tick. With a step of 1/64 s at 128 tick, the physics engine simulates on every
// other tick, and a grenade's bounces, distance and time to come to rest are those of 64 tick.
//
// doi_physics_timestep sets the step, 0 leaves the game's. The plugin sets it again after each map
// start, as the game resets it then.

#include <sourcemod>
#include <sdktools>
#include <doi>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name        = "DOI physics timestep",
    author      = "DOI revival project",
    description = "Keep the physics step of 64 tick at higher tickrates",
    version     = "1.0",
    url         = "https://rev-crew.info"
};

ConVar g_timestep;
GameData g_gamedata;
Handle g_getStep;
Handle g_setStep;

public void OnPluginStart()
{
    DOI_RequireGame();
    g_gamedata = new GameData("doi_physics_timestep.games");
    if (g_gamedata == null)
        SetFailState("Can't load gamedata/doi_physics_timestep.games.txt");
    // IPhysicsEnvironment::GetSimulationTimestep and SetSimulationTimestep
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Virtual, "GetSimulationTimestep"))
        SetFailState("No offset of GetSimulationTimestep in the gamedata");
    PrepSDKCall_SetReturnInfo(SDKType_Float, SDKPass_Plain);
    g_getStep = EndPrepSDKCall();
    StartPrepSDKCall(SDKCall_Raw);
    if (!PrepSDKCall_SetFromConf(g_gamedata, SDKConf_Virtual, "SetSimulationTimestep"))
        SetFailState("No offset of SetSimulationTimestep in the gamedata");
    PrepSDKCall_AddParameter(SDKType_Float, SDKPass_Plain);
    g_setStep = EndPrepSDKCall();

    g_timestep = CreateConVar("doi_physics_timestep", "0.015625",
        "The step of the physics simulation in seconds, at least the tick's interval; 0 for the game's, the tick's interval",
        _, true, 0.0, true, 0.1);
    g_timestep.AddChangeHook(OnTimestepChanged);
    // A plugin loaded on a running map
    ApplyTimestep();
}

public void OnMapStart()
{
    ApplyTimestep();
}

void OnTimestepChanged(ConVar convar, const char[] oldValue, const char[] newValue)
{
    ApplyTimestep();
}

void ApplyTimestep()
{
    // The physics environment, which the game creates anew at every map start
    Address env = g_gamedata.GetAddress("physenv");
    if (env == Address_Null)
        return;
    float step = g_timestep.FloatValue;
    float interval = GetTickInterval();
    // The game's: 0, or a step shorter than a tick, which the physics would simulate several times
    // per tick to no avail
    if (step < interval)
        step = interval;
    float current = SDKCall(g_getStep, env);
    if (current != step)
    {
        SDKCall(g_setStep, env, step);
        LogMessage("Physics step %.6f s instead of %.6f s, tick interval %.6f s", step, current, interval);
    }
}
