// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Keeps the step of the physics simulation (VPhysics) at 1/64 s when the server runs at a higher
// tickrate, so that physics objects behave as they do at the game's 64 tick, in Day of Infamy and
// Insurgency, which set it the same way.
//
// At every map start, the game sets the physics step to the tick's interval (CPhysicsHook::
// LevelInitPreEntity: interval / (floor(interval * 63) + 1)), so at 128 tick the physics runs at
// 1/128 s. Grenades, which are physics objects, then bounce a lot more: their contacts were made for
// the step of 64 tick. With a step of 1/64 s at 128 tick, the physics engine simulates on every
// other tick, and a grenade's bounces, distance and time to come to rest are those of 64 tick.
//
// nwi_physics_timestep sets the step, 0 leaves the game's. The plugin sets it again after each map
// start, as the game resets it then, through nwi_gamedata.smx (nwi_gamedata.inc).

#include <sourcemod>
#include <nwi>
#include <nwi_gamedata>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name        = "NWI physics timestep",
    author      = "DOI revival project",
    description = "Keep the physics step of 64 tick at higher tickrates",
    version     = "1.1",
    url         = "https://rev-crew.info"
};

ConVar g_timestep;

public void OnPluginStart()
{
    NWI_RequireGame();
    g_timestep = CreateConVar("nwi_physics_timestep", "0.015625",
        "The step of the physics simulation in seconds, at least the tick's interval; 0 for the game's, the tick's interval",
        _, true, 0.0, true, 0.1);
    g_timestep.AddChangeHook(OnTimestepChanged);
}

// Also when the plugin is loaded on a running map, once the library is there
public void OnAllPluginsLoaded()
{
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
    float current;
    if (!NWI_GetPhysicsTimestep(current))
        return;
    float step = g_timestep.FloatValue;
    float interval = GetTickInterval();
    // The game's: 0, or a step shorter than a tick, which the physics would simulate several times
    // per tick to no avail
    if (step < interval)
        step = interval;
    if (current != step && NWI_SetPhysicsTimestep(step))
    {
        LogMessage("Physics step %.6f s instead of %.6f s, tick interval %.6f s", step, current, interval);
    }
}
