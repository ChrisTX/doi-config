/**
 * AFK Manager
 * The API of AFK Manager for other plugins
 *
 * SPDX-FileCopyrightText: Rothgar
 * SPDX-FileCopyrightText: Christian Pfeiffer
 * SPDX-License-Identifier: GPL-3.0-only WITH LicenseRef-SourceMod-exception
 *
 * This program is free software; you can redistribute it and/or modify it under
 * the terms of the GNU General Public License, version 3.0, as published by the
 * Free Software Foundation.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
 * FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
 * details.
 *
 * You should have received a copy of the GNU General Public License along with
 * this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * As a special exception, AlliedModders LLC gives you permission to link the
 * code of this program (as well as its derivative works) to "Half-Life 2," the
 * "Source Engine," the "SourcePawn JIT," and any Game MODs that run on software
 * by the Valve Corporation.  You must obey the GNU General Public License in
 * all respects for all other code used.  Additionally, AlliedModders LLC grants
 * this exception to all derivative works.  AlliedModders LLC defines further
 * exceptions, found in LICENSE.txt (as of this writing, version JULY-31-2007),
 * or <http://www.sourcemod.net/license.php>.
 */

#if defined _afkmanager_included
	#endinput
#endif
#define _afkmanager_included

/**
 * Specifies AFK immunity types. Keep this in sync with afk_manager4.sp.
 */
enum AFKImmunity
{
	AFKImmunity_None = 0,
	AFKImmunity_Move = 1,
	AFKImmunity_Kick = 2,
	AFKImmunity_Full = 3
};

/**
 * Sets the AFK immunity type of the client index.
 *
 * @param client	The client index of the player whose immunity type is being set.
 * @param type		The client AFK immunity type.
 * @error			The client index is invalid or AFK immunity type is invalid.
 */
native void AFKM_SetClientImmunity(int client, AFKImmunity type);

/**
 * Gets the AFK spectator team number.
 *
 * @return			The spectator team number.
 */
native int AFKM_GetSpectatorTeam();

/**
 * Gets the current AFK status of the client index.
 *
 * @param client	The client index of the player being checked.
 * @return			The client's AFK status.
 * @error			The client index is invalid.
 */
native bool AFKM_IsClientAFK(int client);

/**
 * Gets the current AFK time in seconds of the client index. If the client
 * has an invalid AFK time -1 will be returned.
 *
 * Examples of clients who would have invalid AFK time values:
 *		Admins with full immunity.
 *		Disconnected clients.
 *		Bots, Fake Clients or Source TV.
 *
 * @param client	The client index of the player being checked.
 * @return			The client's AFK time or -1 if it is invalid.
 * @error			The client index is invalid.
 */
native int AFKM_GetClientAFKTime(int client);

/**
 * Called when AFK Manager starts tracking a client.
 *
 * @param client	The client index of the client in the event.
 * @return			Plugin_Continue to track the client, any other value to
 *					leave the client untracked, like with full immunity.
 */
forward Action AFKM_OnInitializePlayer(int client);

/**
 * Called before AFK Manager moves or kicks a client.
 *
 * Event Names:
 *		"afk_spawn_move"	- The client is moved to spectator for being AFK in spawn.
 *		"afk_move"			- The client is moved to spectator for being AFK.
 *		"afk_kick"			- The client is kicked for being AFK.
 *
 * @param name		The name of the AFK event.
 * @param client	The client index of the client in the event.
 * @return			Plugin_Continue to complete the event, any other value to
 *					cancel it. Plugin_Stop also ends the client's AFK checks.
 */
forward Action AFKM_OnAFKEvent(const char[] name, int client);

/**
 * Called when a client has been set AFK.
 *
 * @param client	The client index of the player being flagged.
 */
forward void AFKM_OnClientAFK(int client);

/**
 * Called when a client is back from AFK.
 *
 * @param client	The client index of the player being flagged.
 */
forward void AFKM_OnClientBack(int client);

public SharedPlugin __pl_afkmanager =
{
	name = "afkmanager",
	file = "afk_manager4.smx",
#if defined REQUIRE_PLUGIN
	required = 1,
#else
	required = 0,
#endif
};

#if !defined REQUIRE_PLUGIN
public void __pl_afkmanager_SetNTVOptional()
{
	MarkNativeAsOptional("AFKM_SetClientImmunity");
	MarkNativeAsOptional("AFKM_GetSpectatorTeam");
	MarkNativeAsOptional("AFKM_IsClientAFK");
	MarkNativeAsOptional("AFKM_GetClientAFKTime");
}
#endif
