// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// What nwi_gamedata.smx calls and hooks in Day of Infamy and Insurgency, for other plugins: the game's
// functions behind natives and forwards, so that only it has the gamedata (gamedata/nwi.games.txt).
//
// A plugin that can't work without it requires the library: `#include <nwi_gamedata>` does, unless
// REQUIRE_PLUGIN is undefined before it, in which case NWI_IsGamedataLoaded() tells whether it's there.

#if defined _nwi_gamedata_included
 #endinput
#endif
#define _nwi_gamedata_included

#define NWI_GAMEDATA_LIBRARY "nwi_gamedata"

// The step of the physics simulation in seconds; false if the physics environment isn't there, e.g.
// before the first map
native bool NWI_GetPhysicsTimestep(float &step);

// Sets the step of the physics simulation; the game sets it anew at every map start. False if the
// physics environment isn't there.
native bool NWI_SetPhysicsTimestep(float step);

// Called when the server sends its details to Steam, which answers the server browsers' queries with
// them: its human players, its maximum (sv_visiblemaxplayers if set) and its bots. Changes of the
// counts go to Steam only, not to status or the server's own answers. bots is all the server's bots;
// afterwards, the server subtracts one for each of them (and for SourceTV) before it passes the bots
// on, so the browsers normally see none: what a plugin adds to bots is what they see.
forward void NWI_OnSteamServerDetails(int &humans, int &maximum, int &bots);

stock bool NWI_IsGamedataLoaded()
{
    return LibraryExists(NWI_GAMEDATA_LIBRARY);
}

// nwi_gamedata.smx itself defines NWI_GAMEDATA_PROVIDER, as it provides the library rather than
// depending on it
#if !defined NWI_GAMEDATA_PROVIDER
public SharedPlugin __pl_nwi_gamedata =
{
    name = NWI_GAMEDATA_LIBRARY,
    file = "nwi_gamedata.smx",
#if defined REQUIRE_PLUGIN
    required = 1,
#else
    required = 0,
#endif
};

#if !defined REQUIRE_PLUGIN
public void __pl_nwi_gamedata_SetNTVOptional()
{
    MarkNativeAsOptional("NWI_GetPhysicsTimestep");
    MarkNativeAsOptional("NWI_SetPhysicsTimestep");
}
#endif
#endif
