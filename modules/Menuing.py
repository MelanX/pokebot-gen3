import random
from typing import NoReturn
import os

from modules.Config import config_battle
from modules.Inputs import PressButton, WaitFrames
from modules.Memory import ReadSymbol, GetTrainer, pokemon_list, type_list, GetParty, GetOpponent, DecodeString, \
    ParsePartyMenu, ParseStartMenu, ParseMenu, ParseBattleCursor, mGBA, ParseTasks, ReadAddress, \
    moves_list
from modules.data.GameState import GameState
from modules.Console import console
from modules.data.TaskFunc import TaskFunc

if mGBA.game in ['Pokémon Ruby', 'Pokémon Sapphire']:
    battle_text = "What should"
else:
    battle_text = "What will"


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
        current_string = DecodeString(ReadSymbol('gDisplayedStringBattle'))
        # mash A until the string changes
        while DecodeString(ReadSymbol('gDisplayedStringBattle')) == current_string:
            PressButton(['A'])


def FleeBattle() -> NoReturn:
    """
    Readable function to select and execute the Run option from the battle menu.
    """
    while GetTrainer()['state'] != GameState.OVERWORLD:
        if "Use next" in DecodeString(ReadSymbol('gDisplayedStringBattle')):
            PressButton(["B"])
        elif battle_text in DecodeString(ReadSymbol('gDisplayedStringBattle')):
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

    matchups = type_list[move["type"]]
    category = matchups["category"]

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
    power *= stat_calc

    return power


def isValidMove(move: dict) -> bool:
    return move['name'] not in config_battle['banned_moves'] and move['power'] > 0


def CalculateNewMoveViability(mon: dict, new_move: dict) -> int:
    """
    Function that judges the move a Pokemon is trying to learn against its moveset and returns the index of the worst
    move of the bunch.

    :param mon: The dict containing the Pokemon's info.
    :param new_move: The move that the mon is trying to learn
    :return: The index of the move to select.
    """
    # determine how the damage formula will be affected by the mon's current stats
    attack_stat = {
        'Physical': mon['stats']['attack'],
        'Special': mon['stats']['spAttack'],
        'a-': 0,
        'a+': 0
    }
    # get the effective power of each move
    move_power = []
    full_moveset = list(mon['moves'])
    full_moveset.append(new_move)
    for move in full_moveset:
        power = new_move['power'] * attack_stat[move['kind']]
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
    if new_move['type'] in [m['type'] for m in mon['moves']] and min(move_power) > 0:
        weakest_move_power = None
        for i in range(len(full_moveset)):
            if full_moveset[i]['type'] == new_move['type']:
                if weakest_move_power is None:
                    weakest_move = i
                    weakest_move_power = move_power[i]
                else:
                    if move_power[i] < weakest_move_power:
                        weakest_move = i
                        weakest_move_power = move_power[i]
    console.print(f"Move to replace is {full_moveset[weakest_move]['name']} with a calculated power of {weakest_move_power}")

    return weakest_move


def FindEffectiveMove(ally: dict, foe: dict) -> dict:
    """
    Finds the best move for the ally to use on the foe.

    :param ally: The pokemon being used to battle.
    :param foe: The pokemon being battled.
    :return: A dictionary containing the name of the move to use, the move's index, and the effective power of the move.
    """
    move_power = []
    foe_types = pokemon_list[foe["name"]]["type"]
    foe_defenses = {
        'physical': foe['stats']['defense'],
        'special': foe['stats']['spDefense'],
    }
    ally_types = pokemon_list[ally["name"]]["type"]
    ally_attacks = {
        'physical': foe['stats']['attack'],
        'special': foe['stats']['spAttack'],
    }

    # calculate power of each possible move
    for i, move in enumerate(ally["moves"]):
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
    Function to battle wild Pokémon. This will only battle with the lead pokemon of the party, and will run if it dies
    or runs out of PP.
    :return: Boolean value of whether the battle was won.
    """
    ally_fainted = False
    foe_fainted = False

    while not ally_fainted and not foe_fainted and GetTrainer()['state'] not in (
            GameState.OVERWORLD, GameState.WHITEOUT
    ) and "scurried" not in DecodeString(ReadSymbol('gStringVar4')):
        if GetTrainer()['state'] == GameState.OVERWORLD:
            return True

        best_move = FindEffectiveMove(GetParty()[0], GetOpponent())

        if best_move['power'] < 10:
            console.print('Lead pokemon has no effective moves to battle the foe!')
            FleeBattle()
            return False

        # If effective moves are present, let's fight this thing!
        while battle_text in DecodeString(ReadSymbol("gDisplayedStringBattle")):
            SelectBattleOption(0, cursor_type="gActionSelectionCursor")

        WaitFrames(5)

        console.print('Best move against foe is {} (Effective power is {})'.format(
            best_move['name'],
            best_move['power']
        ))

        SelectBattleOption(best_move['index'], cursor_type='gMoveSelectionCursor')

        WaitFrames(5)

        while (
                GetTrainer()["state"] != GameState.OVERWORLD and
                battle_text not in DecodeString(ReadSymbol('gDisplayedStringBattle')) and
                "whited out!" not in DecodeString(ReadSymbol('gDisplayedStringBattle'))
        ):
            while GetTrainer()["state"] == GameState.EVOLUTION:
                if config_battle['stop_evolution']:
                    PressButton(['B'])
                else:
                    PressButton(['A'])
            if 'Delete a move' not in DecodeString(ReadSymbol('gDisplayedStringBattle')):
                PressButton(['B'])
                WaitFrames(1)
            if 'Delete a move' in DecodeString(ReadSymbol('gDisplayedStringBattle')):
                HandleMoveLearn()

        ally_fainted = GetParty()[0]['stats']['hp'] == 0
        foe_fainted = GetOpponent()['stats']['hp'] == 0

    if ally_fainted and "whited out!" not in DecodeString(ReadSymbol('gDisplayedStringBattle')):
        console.print('Lead Pokemon fainted!')
        FleeBattle()
        return False
    if (
            GetTrainer()['state'] == GameState.WHITEOUT or
            'scurried' in DecodeString(ReadSymbol('gStringVar4')) or
            "whited out!" in DecodeString(ReadSymbol('gDisplayedStringBattle'))):
        console.print("All pokemon have fainted.")
        os._exit(0)
    return True


def HandleMoveLearn():
    match config_battle['new_move']:
        case 'stop':
            console.print('New move trying to be learned, stopping bot...')
            input('Press enter to exit...')
            os._exit(0)
        case 'cancel':
            while GetTrainer()['state'] != GameState.OVERWORLD:
                while GetTrainer()['state'] == GameState.EVOLUTION:
                    if config_battle['stop_evolution']:
                        PressButton(['B'])
                    else:
                        PressButton(['A'])
                if 'Stop learning' not in DecodeString(ReadSymbol('gDisplayedStringBattle')):
                    PressButton(['B'])
                else:
                    PressButton(['A'])
        case 'learn_best':
            on_learn_screen = False
            while not on_learn_screen:
                for task in ParseTasks():
                    if task['task_func'] == TaskFunc.LEARN_MOVE:
                        if task['is_active']:
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
            while GetTrainer()['state'] != GameState.BATTLE:
                PressButton(['A'])
            while "Stop learning" in DecodeString(ReadSymbol('gDisplayedStringBattle')):
                PressButton(['A'])

        case _:
            console.print("Config new_move_mode invalid.")


def CheckForPickup() -> NoReturn:
    """
    Function that handles pickup farming.
    """
    try:
        pickup_threshold = config["pickup_threshold"]
    except:
        pickup_threshold = 1
    pokemon_with_pickup = 0
    pokemon_with_pickup_and_item = []
    party = GetParty()
    for i in range(len(party)):
        if party[i]['ability'] == "Pickup":
            pokemon_with_pickup += 1
            if party[i]['item']['name'] != 'None':
                pokemon_with_pickup_and_item.append(i)
    if pokemon_with_pickup < pickup_threshold:
        console.print(
            "The pickup threshold is higher than the number of pokemon in the party with pickup, so the latter number will be used.")
        pickup_threshold = pokemon_with_pickup
    if len(pokemon_with_pickup_and_item) >= pickup_threshold:
        console.print("Pickup threshold is met! Gathering items.")
        TakePickupItems(pokemon_with_pickup_and_item)


def TakePickupItems(pokemon_indices: list):
    """
    Function that takes items from pokemon that have the Pickup ability.

    :param pokemon_indices: The list of indices representing the pokemon to take items from.
    """
    current_menu = identifyMenu()
    while current_menu != 'start_menu':
        if current_menu == 'battle_action_menu':
            FleeBattle()
        PressButton(['B'])
        WaitFrames(6)
        PressButton(['Start'])
        WaitFrames(6)
        current_menu = identifyMenu()
    # this bit mashes A until the party menu is active
    while identifyMenu() != 'party_menu':
        NavigateStartMenu(1)
        PressButton(["A"])
    for idx in pokemon_indices:
        while ParsePartyMenu()['slot_id'] != idx:
            if ParsePartyMenu()['slot_id'] > idx:
                PressButton(["Up"])
            else:
                PressButton(["Down"])
        while "Choose a" in DecodeString(ReadSymbol('gStringVar4')):
            PressButton(["A"])
        while "Do what with this" in DecodeString(ReadSymbol('gStringVar4')):
            NavigateMenu(2)
        while "Do what with an" in DecodeString(ReadSymbol('gStringVar4')):
            NavigateMenu(1)
        while "Received the" in DecodeString(ReadSymbol('gStringVar4')):
            PressButton(['B'])
    while identifyMenu() == 'party_menu':
        PressButton(['B'])
    while identifyMenu() == 'start_menu':
        PressButton(['B'])


def NavigateStartMenu(desired_index: int) -> NoReturn:
    """
    Opens the start menu and moves to the option with the desired index from the menu.

    :param desired_index: The index of the option to select from the menu.
    """
    current_cursor_position = ParseStartMenuCursorPos()
    while current_cursor_position != desired_index:
        if current_cursor_position < desired_index:
            PressButton(["Down"])
        else:
            PressButton(['Up'])
        current_cursor_position = ParseStartMenuCursorPos()


def GetStartMenuCursorPos():
    """
    Helper function to get the position of the start menu cursor in a readable way to clean up the code.
    """
    return int.from_bytes(ReadSymbol('sStartMenuCursorPos'), 'big')


def NavigateMenu(desired_index: int) -> NoReturn:
    """
    Given an index, attempts to navigate to the index and press A.
    """
    if desired_index > ParseMenu()['maxCursorPos'] or desired_index < ParseMenu()['minCursorPos']:
        console.print("Can't select this option.")
        return
    while ParseMenu()['cursorPos'] != desired_index:
        if ParseMenu()['cursorPos'] > desired_index:
            PressButton(["Up"])
        else:
            PressButton(["Down"])
    PressButton(["A"])


def identifyMenu() -> str:
    current_cursor_states = GetCursorStates()
    directions = ['Up', 'Right', 'Down', 'Left']
    directions.remove(GetTrainer()['facing'])
    PressButton([random.choice(directions)])
    WaitFrames(6)
    new_cursor_states = GetCursorStates()
    changed_cursors = []
    while new_cursor_states == current_cursor_states:
        directions = ['Up', 'Right', 'Down', 'Left']
        directions.remove(GetTrainer()['facing'])
        PressButton([random.choice(directions)])
        WaitFrames(6)
        new_cursor_states = GetCursorStates()
    for c in new_cursor_states.keys():
        if new_cursor_states[c] != current_cursor_states[c]:
            if c not in changed_cursors:
                changed_cursors.append(c)
    match changed_cursors[0]:
        case 'start_menu_cursor':
            return "start_menu"
        case 'party_menu_cursor':
            return "party_menu"
        case 'menu_cursor':
            return "misc_menu"
        case 'battle_action_cursor':
            return "battle_action_menu"
        case 'battle_move_cursor':
            return "battle_move_menu"
        case 'trainer_facing':
            return "overworld"
        case 'trainer_coords':
            return "overworld"
        case _:
            print("menu without match")
            os._exit(69)
