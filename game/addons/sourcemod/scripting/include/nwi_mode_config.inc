// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// The game mode, as nwi_mode_config.smx knows it, for other plugins: the mode's name as the game
// knows it (e.g. stronghold, checkpoint) and its category, coop, pvp or solo. The mode is known from
// the first map start on; a plugin loaded later knows it once the next map starts.
//
//     #include <nwi_mode_config>
//
//     public void NWI_OnGameModeChanged(const char[] mode, const char[] category, const char[] previous)
//     {
//         ...
//     }
//
// A plugin that can't work without it requires the library: `#include <nwi_mode_config>` does,
// unless REQUIRE_PLUGIN is undefined before it, in which case NWI_IsGameModeConfigLoaded() tells
// whether it's there.

#if defined _nwi_mode_config_included
 #endinput
#endif
#define _nwi_mode_config_included

#define NWI_MODE_CONFIG_LIBRARY "nwi_mode_config"
// Long enough for any game mode's name and category
#define NWI_MODE_LENGTH 32

// The current game mode, e.g. "stronghold"; false and an empty string before the first map start
native bool NWI_GetGameMode(char[] mode, int maxlength);

// The current game mode's category: "coop", "pvp" or "solo"; false and an empty string if the game
// mode isn't known yet, or if its category isn't (a mode the plugin doesn't know, and
// nwi_mode_category empty)
native bool NWI_GetGameModeCategory(char[] category, int maxlength);

// Called when a map starts in another game mode than the previous map, and at the first map start
// (previous empty), after the game mode's configs were queued to run
forward void NWI_OnGameModeChanged(const char[] mode, const char[] category, const char[] previous);

stock bool NWI_IsGameModeConfigLoaded()
{
    return LibraryExists(NWI_MODE_CONFIG_LIBRARY);
}

// nwi_mode_config.smx itself defines NWI_MODE_CONFIG_PROVIDER, as it provides the library rather than
// depending on it
#if !defined NWI_MODE_CONFIG_PROVIDER
public SharedPlugin __pl_nwi_mode_config =
{
    name = NWI_MODE_CONFIG_LIBRARY,
    file = "nwi_mode_config.smx",
#if defined REQUIRE_PLUGIN
    required = 1,
#else
    required = 0,
#endif
};

#if !defined REQUIRE_PLUGIN
public void __pl_nwi_mode_config_SetNTVOptional()
{
    MarkNativeAsOptional("NWI_GetGameMode");
    MarkNativeAsOptional("NWI_GetGameModeCategory");
}
#endif
#endif
