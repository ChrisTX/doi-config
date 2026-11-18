// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// The human players' network statistics that status doesn't show, for the servers' metrics
// (nwi-server metrics), in Day of Infamy and Insurgency.
//
// status shows a player's ping and packet loss, but not choke: the packets the server or the player
// held back, as the other's rate (rate, cl_cmdrate, cl_updaterate) didn't allow them yet. Choke of
// the server's packets, what a player's net_graph shows as choke, means the player gets fewer updates
// than the tick: the server's rates are too low for its tick, or the player's own setting is.
//
// The server command nwi_netstats, of the server's console and RCON only, prints a header and a line
// of each human player, with their average choke as a fraction of the packets, of the server's
// packets to the player (out) and of the player's to the server (in):
//
//     nwi_netstats userid choke_out choke_in
//     9 0.0000 0.0125
//
// Further columns go at the end, under their name in the header, which the metrics read the columns
// by.

#include <sourcemod>
#include <nwi>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name        = "NWI network statistics",
    author      = "DOI revival project",
    description = "The human players' choke for the servers' metrics",
    version     = "1.0",
    url         = "https://rev-crew.info"
};

public void OnPluginStart()
{
    NWI_RequireGame();
    RegServerCmd("nwi_netstats", Command_NetStats,
        "The human players' choke of the server's packets and of theirs, for the servers' metrics");
}

Action Command_NetStats(int args)
{
    PrintToServer("nwi_netstats userid choke_out choke_in");
    for (int client = 1; client <= MaxClients; client++)
    {
        // Bots and SourceTV have no network channel
        if (!IsClientConnected(client) || IsFakeClient(client))
            continue;
        PrintToServer("%d %.4f %.4f", GetClientUserId(client),
            GetClientAvgChoke(client, NetFlow_Outgoing),
            GetClientAvgChoke(client, NetFlow_Incoming));
    }
    return Plugin_Handled;
}
