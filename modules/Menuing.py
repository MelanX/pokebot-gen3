import os
import struct
from typing import NoReturn

from modules.Config import config_battle
from modules.Inputs import PressButton, WaitFrames
from modules.Memory import ReadSymbol, GetGameState, pokemon_list, type_list, GetParty, GetOpponent, DecodeString, \
    GetPartyMenuCursorPos, ParseStartMenu, ParseMenu, ParseBattleCursor, mGBA, ParseTasks, ReadMemory, \
    moves_list, ParseMain, GameState, TaskFunc, GetTaskFunc
from modules.Console import console

if mGBA.game in ['Pokémon Ruby', 'Pokémon Sapphire']:
    battle_text = 'What should'  # TODO English only
else:
    battle_text = 'What will'  # TODO English only


def SelectBattleOption(desired_option: int, cursor_type: str = 'gActionSelectionCursor') -> NoReturn:
    """
    Takes a desired battle menu option, navigates to it, and presses it.

    :param desired_option: The desired index for the selection. For the base battle menu, 0 will be FIGHT, 1 will be
    BAG, 2 will be PKMN, and 3 will be RUN.
    :param cursor_type: The symbol to use for the cursor. This is different between selecting moves and selecting battle
     options.
    """
    while ParseBattleCursor(cursor_type) != desired_option:
        match (ParseBattleCursor(cursor_type) % 2) - (desired_option % 2):
            case - 1:
                PressButton(['Right'])
            case 1:
                PressButton(['Left'])
        match (ParseBattleCursor(cursor_type) // 2) - (desired_option // 2):
            case - 1:
                PressButton(['Down'])
            case 1:
                PressButton(['Up'])
            case 0:
                pass
    if ParseBattleCursor(cursor_type) == desired_option:
        # get current displayed string
        current_string = DecodeString(ReadSymbol('gDisplayedStringBattle'))  # TODO English only
        # mash A until the string changes
        while DecodeString(ReadSymbol('gDisplayedStringBattle')) == current_string:  # TODO English only
            PressButton(['A'])


def FleeBattle() -> NoReturn:
    """
    Readable function to select and execute the Run option from the battle menu.
    """
    while GetGameState() != GameState.OVERWORLD:
        if 'Use next' in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
            PressButton(['B'])
        elif battle_text in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
            SelectBattleOption(3, cursor_type='gActionSelectionCursor')
        else:
            PressButton(['B'])


def getMovePower(move, ally_types, foe_types, ally_attacks, foe_defenses) -> float:
    """
    function to calculate effective power of a move

    """
    power = move['power']

    # Ignore banned moves and those with 0 PP
    if (not isValidMove(move)) or (move['remaining_pp'] == 0):
        return 0

    matchups = type_list[move['type']]
    category = matchups['category']

    for foe_type in foe_types:
        if foe_type in matchups['immunes']:
            return 0
        elif foe_type in matchups['weaknesses']:
            power *= 0.5
        elif foe_type in matchups['strengths']:
            power *= 2

    # STAB (same-type attack bonus)
    if move['type'] in ally_types:
        power *= 1.5

    # calculating attack/defense effect
    stat_calc = ally_attacks[category] / foe_defenses[category]
    #console.print('Move {} has base power of {} and stat bonus of {}'.format(
    #    move['name'],
    #    power,
    #    stat_calc))
    power *= stat_calc

    return power


def isValidMove(move: dict) -> bool:
    return move['name'] not in config_battle['banned_moves'] and move['power'] > 0


def CalculateNewMoveViability(mon: dict, new_move: dict) -> int:
    """
    Function that judges the move a Pokémon is trying to learn against its moveset and returns the index of the worst
    move of the bunch.

    :param mon: The dict containing the Pokémon's info.
    :param new_move: The move that the mon is trying to learn
    :return: The index of the move to select.
    """
    # exit learning move if new move is banned or has 0 power
    if new_move['power'] == 0 or new_move['name'] in config_battle['banned_moves']:
        console.print('New move has base power of 0, so {} will skip learning it.'.format(mon['name']))
        return 4
    # determine how the damage formula will be affected by the mon's current stats
    attack_stat = {
        'Physical': mon['stats']['attack'],
        'Special': mon['stats']['spAttack'],
    }
    # get the effective power of each move
    move_power = []
    full_moveset = list(mon['moves'])
    full_moveset.append(new_move)
    for move in full_moveset:
        attack_type = move['kind']
        match attack_type:
            case 'Physical':
                attack_bonus = mon['stats']['attack']
            case 'Special':
                attack_bonus = mon['stats']['spAttack']
            case _:
                attack_bonus = 0
        power = move['power'] * attack_bonus
        if move['type'] in mon['type']:
            power *= 1.5
        if move['name'] in config_battle['banned_moves']:
            power = 0
        move_power.append(power)
    # find the weakest move of the bunch
    weakest_move_power = min(move_power)
    weakest_move = move_power.index(weakest_move_power)
    # try and aim for good coverage- it's generally better to have a wide array of move types than 4 moves of the same
    # type
    redundant_type_moves = []
    existing_move_types = {}
    for move in full_moveset:
        if move['power'] == 0:
            continue
        if move['type'] not in existing_move_types:
            existing_move_types[move['type']] = move
        else:
            if not redundant_type_moves:
                redundant_type_moves.append(existing_move_types[move['type']])
            redundant_type_moves.append(move)
    if weakest_move_power > 0 and redundant_type_moves:
        redundant_move_power = []
        for move in redundant_type_moves:
            attack_type = move['kind']
            match attack_type:
                case 'Physical':
                    attack_bonus = mon['stats']['attack']
                case 'Special':
                    attack_bonus = mon['stats']['spAttack']
                case _:
                    attack_bonus = 0
            power = move['power'] * attack_bonus
            if move['type'] in mon['type']:
                power *= 1.5
            if move['name'] in config_battle['banned_moves']:
                power = 0
            redundant_move_power.append(power)
        weakest_move_power = min(redundant_move_power)
        weakest_move = full_moveset.index(redundant_type_moves[redundant_move_power.index(weakest_move_power)])
        console.print('Opting to replace a move that has a redundant type so as to maximize coverage.')
    console.print('Move to replace is {} with a calculated power of {}'.format(
        full_moveset[weakest_move]['name'],
        weakest_move_power
    ))
    return weakest_move


def FindEffectiveMove(ally: dict, foe: dict) -> dict:
    """
    Finds the best move for the ally to use on the foe.

    :param ally: The Pokémon being used to battle.
    :param foe: The Pokémon being battled.
    :return: A dictionary containing the name of the move to use, the move's index, and the effective power of the move.
    """
    move_power = []
    foe_types = pokemon_list[foe['name']]['type']
    foe_defenses = {
        'physical': foe['stats']['defense'],
        'special': foe['stats']['spDefense'],
    }
    ally_types = pokemon_list[ally['name']]['type']
    ally_attacks = {
        'physical': foe['stats']['attack'],
        'special': foe['stats']['spAttack'],
    }

    # calculate power of each possible move
    for i, move in enumerate(ally['moves']):
        move_power.append(getMovePower(move, ally_types, foe_types, ally_attacks, foe_defenses))

    # calculate best move and return info
    best_move_index = move_power.index(max(move_power))
    return {
        'name': ally['moves'][best_move_index]['name'],
        'index': best_move_index,
        'power': max(move_power),
    }


def BattleOpponent() -> bool:
    """
    Function to battle wild Pokémon. This will only battle with the lead Pokémon of the party, and will run if it dies
    or runs out of PP.
    :return: Boolean value of whether the battle was won.
    """
    ally_fainted = False
    foe_fainted = False

    while (
            not ally_fainted and
            not foe_fainted and
            GetGameState() != GameState.OVERWORLD and
            'scurried' not in DecodeString(ReadSymbol('gStringVar4'))  # TODO English only
    ):
        if GetGameState() == GameState.OVERWORLD:
            return True

        best_move = FindEffectiveMove(GetParty()[0], GetOpponent())

        if best_move['power'] == 0:
            console.print('Lead Pokémon has no effective moves to battle the foe!')
            FleeBattle()
            return False

        # If effective moves are present, let's fight this thing!
        while battle_text in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
            SelectBattleOption(0, cursor_type='gActionSelectionCursor')

        WaitFrames(5)

        console.print('Best move against foe is {} (Effective power is {:.2f})'.format(
            best_move['name'],
            best_move['power']
        ))

        SelectBattleOption(best_move['index'], cursor_type='gMoveSelectionCursor')

        WaitFrames(5)

        while (
                GetGameState() != GameState.OVERWORLD and
                battle_text not in DecodeString(ReadSymbol('gDisplayedStringBattle')) and
                'whited out!' not in DecodeString(ReadSymbol('gDisplayedStringBattle'))  # TODO English only
        ):
            while GetGameState() == GameState.EVOLUTION:
                if config_battle['stop_evolution']:
                    PressButton(['B'])
                else:
                    PressButton(['A'])
                if 'elete a move' in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                    break
            if 'elete a move' not in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                PressButton(['B'])
                WaitFrames(1)
            if 'elete a move' in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                HandleMoveLearn()

        ally_fainted = GetParty()[0]['stats']['hp'] == 0
        foe_fainted = GetOpponent()['stats']['hp'] == 0

    if ally_fainted:
        console.print('Lead Pokémon fainted!')
        party = GetParty()
        if sum([party[key]['stats']['hp'] for key in party.keys()]) == 0:
            console.print('All Pokémon have fainted.')
            os._exit(0)
        FleeBattle()
        return False
    else:
        while GetGameState() != GameState.OVERWORLD:
            while GetGameState() == GameState.EVOLUTION:
                if config_battle['stop_evolution']:
                    PressButton(['B'])
                else:
                    PressButton(['A'])
            if 'Delete a move' not in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                PressButton(['B'])
                WaitFrames(1)
            if 'Delete a move' in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                HandleMoveLearn()
    return True


def HandleMoveLearn():
    match config_battle['new_move']:
        case 'stop':
            console.print('New move trying to be learned, stopping bot...')
            input('Press enter to exit...')
            os._exit(0)
        case 'cancel':
            while GetGameState() != GameState.OVERWORLD:
                while GetGameState() == GameState.EVOLUTION:
                    if config_battle['stop_evolution']:
                        PressButton(['B'])
                    else:
                        PressButton(['A'])
                if 'Stop learning' not in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                    PressButton(['B'])
                else:
                    PressButton(['A'])
        case 'learn_best':
            on_learn_screen = False
            while not on_learn_screen:
                for task in ParseTasks():
                    if GetTaskFunc(task['func']) == TaskFunc.LEARN_MOVE:
                        if task['isActive']:
                            on_learn_screen = True
                            break
                PressButton(['A'])

            learning_mon = GetLearningMon()
            learning_move = GetLearningMove()
            worst_move = CalculateNewMoveViability(learning_mon, learning_move)
            while GetMoveLearningCursorPos() != worst_move:
                if GetMoveLearningCursorPos() > worst_move:
                    PressButton(['Up'])
                else:
                    PressButton(['Down'])
            while GetGameState() != GameState.BATTLE:
                PressButton(['A'])
            for i in range(30):
                if 'Stop learning' not in DecodeString(ReadSymbol('gDisplayedStringBattle')) and 'Poof!' not in \
                        DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                    WaitFrames(1)
                    continue
                break
            while 'Stop learning' in DecodeString(ReadSymbol('gDisplayedStringBattle')):  # TODO English only
                PressButton(['A'])


def GetLearningMon() -> dict:
    match mGBA.game:
        case 'Pokémon FireRed' | 'Pokémon LeafGreen':
            if ParseMain()['callback_1'] == 'BattleMainCB1':
                idx = int.from_bytes(ReadMemory(
                    struct.unpack('<I', ReadSymbol('gBattleStruct'))[0], offset=0x10, size=1))
            else:
                console.print('Not yet implemented...')
                os._exit(1)
        case 'Pokémon Emerald':
            idx = int.from_bytes(ReadMemory(
                struct.unpack('<I', ReadSymbol('sMonSummaryScreen'))[0], offset=0x40BE, size=1))
        case 'Pokémon Ruby' | 'Pokémon Sapphire':
            idx = int.from_bytes(ReadSymbol('gSharedMem', offset=0x18009, size=1))
    return GetParty()[idx]


def GetLearningMove() -> dict:
    """
    helper function that returns the move trying to be learned
    """
    match mGBA.game:
        case 'Pokémon Emerald':
            return moves_list[struct.unpack('<H', ReadMemory(
                struct.unpack('<I', ReadSymbol('sMonSummaryScreen'))[0], offset=0x40C4, size=2))[0]]
        case 'Pokémon FireRed' | 'Pokémon LeafGreen':
            return moves_list[struct.unpack('<H', ReadSymbol('gMoveToLearn'))[0]]
        case 'Pokémon Ruby' | 'Pokémon Sapphire':
            return moves_list[int.from_bytes(ReadSymbol('gMoveToLearn', size=1))]


def GetMoveLearningCursorPos() -> int:
    """
    helper function that returns the position of the move learning cursor
    """
    match mGBA.game:
        case 'Pokémon Emerald':
            return int.from_bytes(ReadMemory(
                struct.unpack('<I', ReadSymbol('sMonSummaryScreen'))[0], offset=0x40C6, size=1))
        case 'Pokémon FireRed' | 'Pokémon LeafGreen':
            return int.from_bytes(ReadSymbol('sMoveSelectionCursorPos'))
        case 'Pokémon Ruby' | 'Pokémon Sapphire':
            return int.from_bytes(ReadSymbol('gSharedMem', offset=0x18079, size=1))


def CheckForPickup() -> NoReturn:
    """
    Function that handles pickup farming.
    """
    try:
        pickup_threshold = config_battle['pickup_threshold']
    except:
        pickup_threshold = 1
    pokemon_with_pickup = 0
    pokemon_with_pickup_and_item = []
    party = GetParty()
    for i in range(len(party)):
        if party[i]['ability'] == 'Pickup':
            pokemon_with_pickup += 1
            if party[i]['item']['name'] != 'None':
                pokemon_with_pickup_and_item.append(i)
    if pickup_threshold > pokemon_with_pickup > 0:
        pickup_threshold = pokemon_with_pickup
    if len(pokemon_with_pickup_and_item) >= pickup_threshold:
        console.print('Pickup threshold is met! Gathering items.')
        TakePickupItems(pokemon_with_pickup_and_item)


def TakePickupItems(pokemon_indices: list):
    """
    Function that takes items from Pokémon that have the Pickup ability.

    :param pokemon_indices: The list of indices representing the Pokémon to take items from.
    """
    NavigateStartMenu(1)
    while not PartyMenuIsOpen():
        PressButton(['A'])
    for idx in pokemon_indices:
        while GetPartyMenuCursorPos()['slot_id'] != idx:
            if GetPartyMenuCursorPos()['slot_id'] > idx:
                PressButton(['Up'])
            else:
                PressButton(["Down"])
        if mGBA.game in ['Pokémon Emerald', 'Pokémon FireRed', 'Pokémon LeafGreen']:
            while 'Choose a' in DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                PressButton(['A'])
            while 'Do what with' in DecodeString(ReadSymbol('gStringVar4')) and not 'an item?' in \
                                    DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                NavigateMenu(2)
            while 'Do what with an' in DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                NavigateMenu(1)
            while 'Received the' in DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                PressButton(['B'])
        else:
            while 'SUB_8089D94' not in [task['func'] for task in ParseTasks()]:
                PressButton(['A'])
                WaitFrames(1)
            while 'SUB_8089D94' in [task['func'] for task in ParseTasks()] and \
                    not 'SUB_808A060' in [task['func'] for task in ParseTasks()]:
                NavigateMenu(2)
                WaitFrames(1)
            while 'SUB_808A060' in [task['func'] for task in ParseTasks()]:
                NavigateMenu(1)
                WaitFrames(1)
            while TaskFunc.PARTY_MENU not in [GetTaskFunc(task['func']) for task in ParseTasks()]:
                PressButton(['B'])
                WaitFrames(1)
    while GetGameState() != GameState.OVERWORLD or ParseStartMenu()['open']:
        PressButton(['B'])
    for i in range(30):
        if GetGameState() != GameState.OVERWORLD or ParseStartMenu()['open']:
            break
        PressButton(['B'])
    while GetGameState() != GameState.OVERWORLD or ParseStartMenu()['open']:
        PressButton(['B'])


def NavigateStartMenu(desired_index: int) -> NoReturn:
    """
    Opens the start menu and moves to the option with the desired index from the menu.

    :param desired_index: The index of the option to select from the menu.
    """
    while not ParseStartMenu()['open']:
        PressButton(['Start'])
    current_cursor_position = ParseStartMenu()['cursor_pos']
    while current_cursor_position != desired_index:
        if current_cursor_position < desired_index:
            PressButton(['Down'])
        else:
            PressButton(['Up'])
        current_cursor_position = ParseStartMenu()['cursor_pos']


def NavigateMenu(desired_index: int) -> NoReturn:
    """
    Given an index, attempts to navigate to the index and press A.
    """
    if desired_index > ParseMenu()['maxCursorPos'] or desired_index < ParseMenu()['minCursorPos']:
        console.print('Can\'t select this option.')
        return
    while ParseMenu()['cursorPos'] != desired_index:
        if ParseMenu()['cursorPos'] > desired_index:
            PressButton(['Up'])
        else:
            PressButton(['Down'])
    PressButton(['A'])


def PartyMenuIsOpen() -> bool:
    if mGBA.game in ['Pokémon Emerald', 'Pokémon FireRed', 'Pokémon LeafGreen']:
        return GetGameState() == GameState.PARTY_MENU
    else:
        return TaskFunc.PARTY_MENU in [GetTaskFunc(task['func']) for task in ParseTasks()]


def RotatePokemon():
    """
    function to swap out lead battler if PP or HP get too low
    """
    NavigateStartMenu(1)
    while not PartyMenuIsOpen():
        PressButton(['A'])
    party = GetParty()
    new_lead_idx = 0
    for i in range(len(party)):
        if party[i]['stats']['hp'] > 0:
            print('Pokémon {} has hp!'.format(party[i]['name']))
            for move in party[i]['moves']:
                if move['power'] > 0 and move['remaining_pp'] > 0:
                    print('Pokémon {} has usable moves!'.format(party[i]['name']))
                    new_lead_idx = i
                    break
            if new_lead_idx > 0:
                break
    if new_lead_idx > 0:

        while GetPartyMenuCursorPos()['slot_id'] != new_lead_idx:
            if GetPartyMenuCursorPos()['slot_id'] > new_lead_idx:
                PressButton(['Up'])
            else:
                PressButton(['Down'])

        if mGBA.game in ['Pokémon Emerald', 'Pokémon FireRed', 'Pokémon LeafGreen']:
            while 'Choose' in DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                PressButton(['A'])
            while 'Do what with' in DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                NavigateMenu(1)
            while 'Move to' in DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                if GetPartyMenuCursorPos()['slot_id_2'] != 0:
                    PressButton(['Up'])
                else:
                    PressButton(['A'])
            while 'Choose' in DecodeString(ReadSymbol('gStringVar4')):  # TODO English only
                PressButton(['B'])
        else:
            while 'SUB_8089D94' not in [task['func'] for task in ParseTasks()]:
                PressButton(['A'])
                WaitFrames(1)
            while (
                    'SUB_8089D94' in [task['func'] for task in ParseTasks()]
            ) and not (
                    'SUB_808A060' in [task['func'] for task in ParseTasks()] or
                    'HANDLEPARTYMENUSWITCHPOKEMONINPUT' in [task['func'] for task in ParseTasks()]
            ):
                NavigateMenu(1)
                WaitFrames(1)
            while SwitchPokemonActive():
                if GetPartyMenuCursorPos()['slot_id_2'] != 0:
                    PressButton(['Up'])
                else:
                    PressButton(['A'])
                WaitFrames(1)
            while TaskFunc.PARTY_MENU not in [GetTaskFunc(task['func']) for task in ParseTasks()]:
                PressButton(['B'])
                WaitFrames(1)

        while GetGameState() != GameState.OVERWORLD or ParseStartMenu()['open']:
            PressButton(['B'])
        for i in range(30):
            if GetGameState() != GameState.OVERWORLD or ParseStartMenu()['open']:
                break
            PressButton(['B'])
        while GetGameState() != GameState.OVERWORLD or ParseStartMenu()['open']:
            PressButton(['B'])
    else:
        console.print('No Pokémon are fit for battle.')
        os._exit(0)


def SwitchPokemonActive() -> bool:
    """
    helper function to determine if the switch Pokémon menu is active
    """
    tasks = ParseTasks()
    for task in tasks:
        if task['func'] == 'HANDLEPARTYMENUSWITCHPOKEMONINPUT' and task['isActive']:
            return True
    return False
