// The Source SDK's types for Ghidra, through their DWARF: sdk_types.sh compiles this with full debug
// information against a branch of hl2sdk (e.g. doi or insurgency), together with tier1's KeyValues,
// convar and bitbuf, whose functions bring their signatures.
#include "tier1/KeyValues.h"
#include "tier1/bitbuf.h"
#include "tier1/convar.h"
#include "tier1/netadr.h"
#include "tier1/utlbuffer.h"
#include "tier1/utldict.h"
#include "tier1/utlvector.h"

#include "edict.h"
#include "eiface.h"
#include "game/server/iplayerinfo.h"
#include "globalvars_base.h"
#include "iclient.h"
#include "icvar.h"
#include "igameevents.h"
#include "inetchannel.h"
#include "inetchannelinfo.h"
#include "iserver.h"
#include "iserverplugin.h"

// Instantiated, so the templates' layouts are in the DWARF too
template class CUtlVector<char *>;
template class CUtlDict<void *, int>;

// The interfaces Metamod:Source and SourceMod hook with SourceHook, whose vtable layouts come from the
// SDK's headers at compile time: used, so their classes are in the DWARF with their vtable slots
// (vtable_slots.py)
IServerGameDLL *server_game_dll;
IServerGameClients *server_game_clients;
IServerGameEnts *server_game_ents;
IVEngineServer *engine_server;
IPlayerInfoManager *player_info_manager;
IServerPluginHelpers *server_plugin_helpers;
IGameEventManager2 *game_event_manager;
IServer *server;
IClient *client;
ICvar *cvar_interface;
INetChannel *net_channel;
IBotManager *bot_manager;
IPlayerInfo *player_info;
IServerGameTags *server_game_tags;
IServerPluginCallbacks *server_plugin_callbacks;
IGameEvent *game_event;
