  ---
  title: Unleashed Rules FAQ and Clarifications
  url: https://playriftbound.com/en-us/news/rules-and-releases/unleashed-rules-faq-and-clarifications/
  date: 4/29/2026
  set: UNL
  ---

Revised and Clarified Rulings
Triggered Abilities

We’ll start with the most significant and contextual rules change in this update. As of our third rules update, triggered abilities have been changed in their structure: rather than a one clause condition and a potentially multi-clause effect, there are now multiple pieces that need to be considered when putting a triggered ability on the chain and finalizing it. The easiest way to think about these is shifting where the effect and condition split into two components of the triggered ability: instead of at the first comma, it now depends on how the triggered ability is templated. Triggered abilities will have one or more of the following four items in sequence: 

    A trigger condition
    A conditional statement next to the trigger condition
    A “you may” that appears next to the conditional statement
    A cost within instruction next to the “you may”

We can best see this in the example of Piltover Enforcer, the Vi Legend from Unleashed: “[When you conquer], [if you assigned 3 or more excess damage], [you may] [exhaust me to] ready a unit.” This ability contains all four elements in the sequence. 

    A trigger condition: “When you conquer”
    Extra conditional: “If you assigned 3 or more excess damage,”
    A “you may” that appears next to the conditional: “You may,” - this indicates the decision of whether or not to place the ability on the chain
    A cost within instruction next to the “you may”: “Exhaust me to...” - is the cost within instructions that becomes the base cost of the triggered ability. 

We can imagine splitting this ability into two sections: the part including this sequence and the part after it:

Before
	

After
“When you conquer, if you assigned 3 or more 
excess damage, you may exhaust me to”	“ready a unit.”

The second section only becomes a finalized chain item when the first section is fulfilled by the process of finalization; that being the process by which players make choices, pay costs, and check legality for cards and abilities. When the trigger condition and extra conditional are fulfilled and the player decides to place it on the chain, it will become a pending chain item and be queued for finalization. If its controller chooses a legal target and pays the cost during the subsequent finalization, the second section will become a finalized chain item. All it says on the chain is “Ready a unit,” where the unit is the one chosen during finalization.

Triggered abilities, however, don’t need to contain all of the above elements in order for the sequence to follow these rules, as long as the elements that do appear are where they would be based on our understanding of the above sequence.

Let’s look at a few examples:

    Sona, Harmonious reads “At the end of your turn, if I'm at a battlefield, ready up to 4 friendly runes.” “If I’m at a battlefield,” appears where we would expect it to based on the sequence described above, so it is part of the condition and not the effect. The ability can be split into “At the end of your turn, if I’m at a battlefield,” and “ready up to 4 runes.”

    Disarming Rake reads “When you play me, you may kill a gear.” The “you may” appears here where we would expect it to based on the sequence above, so it is the choice of whether or not to place the ability on the chain, and not part of the effect itself. The ability can be split into “When you play me, you may” and “kill a gear.”

    Ekko, Recurrent reads, “[Deathknell][>] Recycle me to ready your runes.” Deathknell is functionally short for “When I die, …” We can translate this to our sequence as “When I die, recycle me to ready your runes.” “Recycle me to” is a cost within instructions that appears where we would expect it to based on our sequence, so it becomes the base cost of the ability when it is placed on the chain and is not part of the effect. The ability can be split into “When I die, recycle me to” and “ready your runes.”

Any of these elements that appear later in the ability than where you would expect based on the sequence do not function in this way. 

    Loose Cannon, the Jinx Legend, reads “At the start of your Beginning Phase, draw 1 if you have one or fewer cards in your hand.” The conditional statement “if you have one or fewer cards in your hand,” does not appear where we would expect in the sequence described above, so it is considered part of the effect and not the condition. This ability can be split into “At the start of your Beginning Phase,” and “draw 1 if you have one of fewer cards in your hand.”

    Ornn, Blacksmith reads “When you play me or when I hold, look at the top 4 cards of your Main Deck. You may reveal a gear from among them and draw it. Then recycle the rest.” The “you may” here doesn’t appear in the appropriate place to be part of the sequence, so it is not a decision made when the ability triggers and instead is made when ability resolves. This ability can be split into “When you play me or when I hold,” and “look at the top 4 cards of your Main Deck. You may reveal a gear from among them and draw it. Then recycle the rest.”

    Insightful Investigator reads “When you play me, choose an opponent. They reveal their hand. You may pay 2 XP to choose a card from their hand. If you do, they discard that card and draw 1.” Here we see the final example, where the ability contains a cost within instructions that does not fall where we would expect it to be for the sequence. This cost within instructions is paid on resolution and not as the base cost of the triggered ability. The ability can be split into “When you play me,” and “Choose an opponent. They reveal their hand. You may pay 2 XP to choose a card from their hand. If you do, they discard that card and draw 1.” The second part of the ability is all one chain item—it resolves it one go, and cannot be reacted to partway through resolution.

One notable effect of this change is that we see a larger difference between two previously similar templates: costs within instructions (“[do X] to [do Y]”) and “if you do” templates. The two templates had some overlap, in that they asked players to perform an action in order to get an effect. The templates, however, were still functionally different before this rules update. Costs don’t care if the game action being performed is replaced, as long as an attempt was made to perform the action.

“If you do” templating is more particular, as seen in cards like Jayce, Man of Progress whose triggered ability begins with, “When you play me, you may kill a friendly gear. If you do, …” Killing the friendly gear in this case is not a cost for the ability, but a game action that a later instruction checks. If the game action is not performed or is replaced, the later instruction will not have its condition fulfilled - the player didn’t “do” it, so “if you do” is not true. 

While this was always the case, now there is even more differentiation, as “if you do” templating isn’t a cost within instructions and therefore cannot be the base cost of the triggered ability. Even if resources are instructed to be spent, as in the case of Draven, Vanquisher (RIP), who reads “When I attack or defend, you may pay [C]. If you do, …” those resources are not a cost and are paid on resolution of the ability and not finalization.
Control of Battlefields and Showdowns

Two areas that were unclear in the rules update were control of battlefields and when Showdowns open. How battlefield control is managed is contradictory in two places: in the control rules under rule 187.4.c., and in the cleanup rules under rule 323.6. To clarify this: rule 323.6. should read, “Players lose control of any controlled battlefields without their Units occupying them if the turn is in an open state and there is no Showdown or Combat ongoing there.” This was our intent, as seen in the patch notes, and the wording of rule 323.6 lagged behind it.
187.4.c.	If a player has no Units at a Battlefield and the turn is in an Open state, they lose Control of that Battlefield in the following cleanup, unless there is a Combat or Showdown ongoing there.
323.6.	

(OLD) 4. If the turn is in an Open State, Battlefields with no Units occupying them and no Showdown or Combat ongoing become Uncontrolled.

(NEW) 4. Players lose control of any controlled Battlefields without their Units occupying them if the turn is in an open state and there is no Showdown or Combat ongoing there.

The second of these areas is how Showdowns are opened. Here, the cleanup rules are correct and take precedence over the other rules. Rule 316.5.b. should read, “A Showdown is marked as staged at a battlefield in the cleanup after the Contested status is applied to that battlefield.” Rule 344.2. should read, “If Control of a battlefield is Contested and there aren’t units controlled by different players there, a Showdown is opened during the Cleanup at the end of the action that caused the battlefield to become Contested.”

For example, if a player moves a unit to a battlefield they don’t control, they will apply the Contested status to that battlefield immediately upon becoming located there, regardless of whether there are units controlled by another player there or not. The battlefield having the Contested status causes a Showdown to be staged there in the following cleanup per rule 323.8. The previous wording of 316.5.b. implied that a Showdown will only be staged at a battlefield if that battlefield is uncontrolled, but the change to how Showdowns become Combats means Showdowns need to be able to be staged when the battlefield is still controlled.
323.8.	6. Mark a Showdown as Staged at each Battlefield that Contested was applied to.
316.5.b.	(OLD) A Showdown is marked as Staged at a Battlefield when the Contested status is applied to a Battlefield with no current controller.

(NEW) A Showdown is marked as staged at a Battlefield in the cleanup after the Contested status is applied to that Battlefield.
344.2.	(OLD) If Control of a Battlefield is Contested and the Battlefield in question is uncontrolled when it becomes Contested, a Showdown is opened during the Cleanup at the end of the action that caused the Battlefield to become Contested.

(NEW) If Control of a Battlefield is Contested and there aren’t units controlled by different players there, a Showdown is opened during the Cleanup at the end of the action that caused the Battlefield to become Contested.
Mandatory Actions and Private Information

Rift Herald is an interesting card. Usually, we don’t print effects like Rift Herald’s Deathknell that don’t say “may.” However, even without the “may,” an important principle that we want to hold for Riftbound is that game effects cannot force a player to perform a game action on an object with specific characteristics whose information status is private.

Imagine if we lived in such a world. When Rift Herald’s Deathknell resolves, your opponent claims to not have a unit in their hand. But what if they do have a unit and they want to try to save it for a more opportune moment? What if playing it would be actively detrimental to them? Suddenly, every time your opponent says they don’t have a card to play that matches the appropriate characteristics it makes you wonder if they’re lying to you. How do you hold them accountable? Do you go over and look at their hand? Do you call a friend to check their hand? If you’re at a tournament, do you call a judge? This is an unsustainable level of paranoia to subject players to. We don’t want that and neither do you.

The following rule will be added in the next rules update and will go into effect now:

    A player cannot be compelled to perform an action on cards whose privacy is secret or private if that action specifies a type or quality of card. If an effect would compel a player to perform an action on cards whose privacy is secret or private, and if that effect specifies a type or quality of card, the player in question may ignore it instead.

Lethal Damage Modification

Elder Dragon’s passive ability reads, “Any amount of your damage is enough to kill enemy units.” This functions to change the definition of lethal damage for those units that have damage marked by you on them. In order to break that down in a technical way, we’ll have to define a few terms.

Lethal damage is an amount of damage such that a unit with it marked will die in a cleanup. This value is defined as being a non-zero amount greater than or equal to a unit’s Might by default. However, some effects may alter it. Any reference to lethal damage, including in the cleanup tasks in rule 323.5. and when assigning Combat damage in rule 460.2.c.3., will be altered in this way. Damage is marked on a unit by a player when a deal action that player is responsible for damages that unit. Damage marked by players is “their damage.”

The combination of these two concepts codifies how Elder Dragon functions. This means Elder Dragon can check damage marked on units by its controller before it enters the board, and that players need only assign one damage to units during the Combat Damage step while they control Elder Dragon.
323.5.	3b. All Units that have non-zero Damage marked on them equalling or exceeding their Might are killed and placed in their owners' Trash.
460.2.c.3.	Units must have lethal damage assigned to them in full before damage is assigned to a different Unit.
Control of Battlefield Abilities

Our first battlefield with a triggered ability anyone can trigger that targets game objects was printed in Unleashed and it has unearthed some strangeness in the battlefield control rules. That battlefield is Abandoned Hall.

Normally, control of a battlefield ability is awarded to the battlefield’s controller, or the turn player if it is uncontrolled, but there are cases where that might not be the case. The intent of the current rules is that a player making choices for a triggered ability of a battlefield means that player controls that ability. This is reflected in a small but easily neglected part of the battlefield ability control rules in “unless otherwise specified.” That should be treated as the following: If an Ability of a Battlefield indicates that a specific player makes a choice, that player takes responsibility for adding it to the chain if applicable and makes all choices required by the ability. They and only they control the ability.

Note that if a battlefield ability requires more than one player to make a choice, that ability will still be controlled by the controller of the battlefield.
Legion

Legion’s change in this rules update is a byproduct of the transition that Riftbound finds itself in. To pull back the curtain, our hope in the future is to reduce the confusion around “play” meaning different things in templating. Unfortunately, this rules update has pulled us in three directions and made things temporarily more confusing. We will communicate these rules in a more comprehensible way in the next rules update. That being said, we recognize that these three technical meanings of play are quite frustrating for players and we’re in the process of paring them down.

For this rules update, we’ll address three functional meanings of “play”, though two of them are aligned in a way that should make them feel like they are functionally similar.

The first meaning is, “resolve an item on the chain.” This is the play that appears in trigger conditions, in cards like Darius, Trifarian and Ravenbloom Student. 

The second meaning is, “finalize an item on the chain.” This is the play that appears in other conditional statements and effects that check if cards have been played, in cards like Battering Ram, Crescent Guardian, and the Legion dependent keyword.

The final meaning of play is, “place an item on the chain and queue it for finalization.” This is the version of play that we see in all other contexts in which play is used as a verb, in cards like Here to Help, Raging Firebrand, and Void Drone.

Having three technical usages of the same word is not ideal, to say the least. This can be seen in the most egregious case with Brynhir Thundersong’s play effect, which reads, “When you play me, opponents can’t play cards this turn.” Using play to mean resolve and also “perform the play game action” in the same card effect has been an abiding source of confusion among players since Origins.

That being said, the usages of “play as game action” and “play as finalize” are functionally aligned---finalizing a card and putting a card on the chain to be queued for finalization are similar actions. Even if we wanted an effect to check for the game action, it would ultimately have to check for finalization because the process of play could be undone during finalization. These timings are similar enough that we hope it will be relatively easy for players to develop an intuition for them. “Play as resolution” is an outlier and it will remain so for this transition period.
Results of Combat

A final point of clarification, the Determine Combat Result task is currently missing a minor but very important part. Rule 461.3.d. should read: There is “No Result” if units were recalled during the Combat Cleanup, if both Players have units present during this task, or if neither player has units present during this task.

For example, if a tie occurred after the Combat Damage step—as in, there were Attackers and Defenders still remaining at the battlefield in the Combat Cleanup and the Attackers were recalled—under the previous wording of rule 461.3.d., the defending player will win the Combat because there are only units controlled by one player located at the battlefield as the task occurs.
461.3.d.	(OLD) There is “No Result” if either both Players have units present during this step, or neither player has units present during this step

(NEW) There is “No Result” if units were recalled during the Combat Cleanup, if both Players have units present during this task, or if neither player has units present during this task.
Frequently Asked Questions

What happens when you conquer Aspirant’s Climb with Green Father and Brush the battlefield when both players are at 8 points? 

If this is the first battlefield that player has scored, they'll draw 1 and the game will continue with both players at 8 points.

If you replace Aspirant’s Climb with Brush via Green Father’s conquer or hold effect, the Victory Score will change immediately as the passive ability of Aspirant’s Climb is no longer in effect, bringing both players to the Victory Score simultaneously. Rules 323.1. and 467. define winning the game as happening during a cleanup when one player has points greater than or equal to the Victory Score and greater than any opponent. If both players are at 8 points, they have not fulfilled both requirements for winning the game. They will need to score additional points in order to win. When they do so, 466.1.b. says “when a player tries to gain a point through a Score, and their current point total is one point from the Victory Score for their Mode of Play or higher, do the following: …” If the point is from Conquering, they will draw 1 instead of gaining the point unless they have scored each battlefield that turn. In effect, every point at or above the Victory Score becomes the final point.
323.1.	1. If a player has points greater than or equal to the Victory Score, and more points than any opponent, that player wins.
467.	When a cleanup occurs and a player has accrued Points greater than or equal to the Victory Score for their Mode of Play, and if they have more points than any opponent, they Win the Game.

What happens if you Brush a Brush? Can you swap back the original battlefield you Brushed?

The Brush token will cease to exist. When swapping back, a player can choose to swap back to any object that was replaced, including the original battlefield.

This is because a replacing game object inherits all of the statuses and conditions of the game object it replaced, per 438.1. A game object can be instructed to “swap back”; the token stops existing and the original card is returned to the space that the token occupied, inheriting all its current effects and statuses per rule 438.7.b. “All of the effects and statuses” includes not only temporary effects applied to the battlefield, but also the relationship between replaced and replacing battlefields.
438.1.	Replacing is the act of Creating a token in the place of another card or token without playing it while inheriting all effects or statuses of the game object it replaced.
438.7.b.	To Swap Back, the token stops existing and the original card is returned to the space that the token just occupied, inheriting all current effects and statuses.

If I play Turn to Dust on an attached Equipment, will the Equipment die in the Beginning Phase?

Yes. The granted Temporary keyword will be active. It will trigger and kill the equipment in its controller’s next Beginning Phase.

Attached Equipment only have their printed rules text made inactive per rules 718.2. and 135.4. This means that any granted rules text will still be active; granted Temporary will trigger and kill attached Equipment and granted Deflect will add [A] to the cost of enemy spells and abilities that target them. Prior to this rules update, all rules text of attached Equipment was inactive.
135.4.	A card’s printed Rules Text is Inactive while that card is Attached to another card.
718.2.	While in this state, the card’s printed Rules Text is Inactive.

If Temporary is granted to an attached Spinning Axe, will it die at the start of my Beginning Phase?

Yes. The Spinning Axe will have two instances of the Temporary keyword - one that is active and one that is inactive. The inactive keyword will not trigger, but the active one will. Alas, Spinning Axe will die.

Multiple instances of the Temporary keyword are redundant per rule 816.2., but that rule refers to the fact that multiple instances that could trigger will only trigger once, as clarified by rule 816.2.a. In the case of granted Temporary on an attached Spinning Axe, that rule isn’t of any concern - there is only one instance of Temporary that could trigger, so it will.

It can help to visualize the attached permanent as it is undergoing these changes, as if it were being digitally simulated. Imagine all of its printed rules text as going gray while it is attached, as it is inactive. Then the granted Temporary keyword, because it is active, is the normal text color for Spinning Axe. There are two colors of Temporary on Spinning Axe, but the grey Temporary doesn’t have any function. We can treat it as if it didn’t exist for the purposes of rule 816.2.a.
816.2.	Multiple instances of Temporary are redundant.
816.2.a.	Regardless of how many instances there are, the ability will only trigger once.

You mentioned rule 187.4.c. earlier and it says “open state”, I don’t remember that in the old rules. What gives?

Control of battlefields cannot be lost while there are items on the chain, per rule 187.4.c. in the Unleashed rules update. This means that spells and abilities that banish and play units, or that kill units as a cost or effect in order to play another unit, will be able to kill or banish units at battlefields and then play the resulting unit to that same battlefield.
187.4.c.	If a player has no Units at a Battlefield and the turn is in an Open state, they lose Control of that Battlefield in the following cleanup, unless there is a Combat or Showdown ongoing there.

Let’s look at some examples:

    I play Cruel Patron, and I have a 1 [M] Recruit alone at a battlefield I control. I choose to kill my Recruit to pay the additional cost of Cruel Patron. Although this causes a cleanup, because there is an item on the chain (Cruel Patron) I don’t lose control of the battlefield. I can choose to play Cruel Patron to that same battlefield with no issue.

    I activate Baited Hook targeting a 4 [M] unit that is alone at a battlefield I control. When Baited Hook resolves, I kill that unit and look at the top 5 cards of my Main Deck. I choose to play a unit from among them, which goes pending on the chain. When Baited Hook’s activated ability resolves, the outstanding cleanup initiates, but I can’t lose control of the battlefield because the played unit is on the chain pending. Once the cleanup finishes, I will finalize the unit and I can choose the battlefield where I killed my 4 [M] unit to play it to.

    I play Arcane Shift targeting my Thousand-Tailed Watcher who is alone at a battlefield I control. As it resolves, Watcher is banished and played to the chain. When Arcane Shift has finished resolving, a cleanup is outstanding and because Watcher is still pending on the chain, control of the battlefield can’t be lost. When finalizing Watcher, the battlefield I banished it from is a valid location to play it to because I still control it.

    There is one final example worth discussing, though the interaction worked similarly prior to this rules update: in the previous rules update, if my Glasc Mixologist died alone in Combat at a battlefield I control, the active Combat at the battlefield prevented me from losing control of the battlefield. Thus I could play the unit from Mixologist’s Deathknell to the same Battlefield it died at. Previously this was only possible in Combat, but as of this rules update the same process will occur whenever Glasc Mixologist dies alone at a battlefield with the same controller, regardless of if there is a Combat there or not.

Can a cleanup happen while I’m finalizing a card or ability?

No. A cleanup cannot occur during the process of finalizing a card or ability.

Finalizing is part of the FEPR process—Finalize, Execute, Pass, Resolve—which is the process that handles items on the chain. Finalizing is the step where you make choices, pay costs, and check legality. Cleanups will occur after adding an item to the chain, after finalizing that item, and after that item resolves. At each point that a cleanup occurs, it will pause the FEPR process until it is complete. However, cleanups will only happen between these steps and never during a step itself.

If I conquer a battlefield with Zilean, Time Mage, can I copy him with my Deceiver legend? Will I make infinite Zileans?

Yes, you can copy Zilean, but you will not make an infinite number. The Deceiver reflexive trigger effect for turning the tokens into copies of Zilean takes place after they are already resolved.

Let’s walk through this step by step. Remember, we are first going to add to the chain and then we will work in reverse order to resolve these things.

    You trigger Deceiver when you score the battlefield, discarding a card and exhausting her as the cost to finalize the trigger.
    When the effect resolves, you play a 0 [M] Reflection token to the chain. 
    Zilean’s replacement effect sees you playing a token and it replaces that event with you playing the token and a copy of that token. Now there are two 0 [M] Reflection tokens waiting on the chain. 
    The Deceiver trigger puts the reflexive trigger on the chain that copies a unit (chosen on finalization) and gives the tokens Temporary.

Remember, you finalize all of these items in the order that they were added to the chain, starting with the two tokens that are placed on the chain in the order of their controller’s choosing. 

So now we work through the above ordering in reverse: 

    As soon as either token is finalized, it resolves immediately. 
    Both tokens enter ready when they resolve this way, because the copy that is generated by Zilean’s replacement effect inherits any modifications (rule 375). 
    Next you finalize the reflexive trigger, choosing a unit to copy. You target Zilean. 
    When it resolves, it will cause the two Reflection tokens to become a copy of Zilean, as well as granting them Temporary—both Reflections receive this modification for the same reason that they are both ready, because of rule 375.

By this point, even if the two tokens become copies of Zilean, there is no subsequent play game action involving tokens to apply their replacement effects to, so they will not be able to cause any further tokens to be produced.
375.	If an event that a Replacement Effect applies to would be modified by a Game Effect, or the results of that event would be modified by a Game Action, the Replacement Effect will inherit those modifications.

If I play Counter Strike in response to my opponent’s Elder Dragon’s play effect, will the chosen unit still die?

No, the unit protected by Counter Strike will not die.

Elder Dragon’s passive ability changes the definition for what is considered lethal damage for a unit, as long as that unit has damage marked by Elder Dragon’s controller on it. However, this doesn’t change the actual amount of damage being dealt. Elder Dragon deals 1 damage to up to one unit at each location—if one of those units has a prevent effect applied to it, that prevent effect will replace as much of that damage as it can. In the case of Counter Strike, it will replace all of the damage. If the damage is entirely prevented, it is never dealt per rule 437.2.a., and thus there is no opportunity for the passive ability of Elder Dragon to apply to that unit.
437.2.a.	The damage being dealt as a result of Preventing can never be less than 0, but can be 0. This is equivalent to not dealing damage.

My opponent plays Elder Dragon and targets my two units at the two battlefields, as well as one of my units in base. If I play Flash in reaction, moving the two units at battlefields to base, will they be dealt damage?

They will not.

Elder Dragon’s play effect has a number of targeting restrictions equal to the number of locations on the board. Its controller chooses up to one enemy unit at each of those locations to target with the ability and each of those units must follow their respective targeting restriction. It is the equivalent to saying “Deal 1 to up to one enemy unit at battlefield A. Deal 1 to up to one enemy unit at battlefield B. Deal 1 to up to one enemy unit in your base. Deal 1 to up to one enemy unit in Opponent A’s Base. …” Each of those targeting restrictions is fulfilled separately for each unit targeted.

If you play Flash in reaction to the play effect of Elder Dragon, any units that are moved to a location other than the one where they were targeted will no longer fulfill the targeting restriction of the Elder Dragon play effect and will be unaffected by the ability as it resolves.

If I play Singularity and my opponent counters it, can I still play Jhin, Meticulous Killer for [C] this turn?

You can. Jhin checks the energy spent to play a spell, not whether that spell resolved. If the energy was spent and the spell became a Finalized Chain Item (and was not undone, for example as part of step 5 of the process of play) then it doesn’t matter if the spell is later countered. The energy wasn’t unspent, even if the spell was countered.

I play Alpha Strike targeting my Master Yi, Unstoppable and splitting 12 damage among three of the four enemy units at battlefields. If my opponent plays Flash in reaction to my Alpha Strike, moving two of the targeted units to base, can they then play Repulse and counter my Alpha Strike?

No, they cannot play Repulse targeting your Alpha Strike. (Except if both of the other chosen units have changed to a non-board zone, such as via the effect of something like Grim Apothecary’s play effect, Heedless Resurrection’s additional cost, or the instructions of Thrill of the Hunt.)

A spell that targets a game object creates a targeting relationship between it and the targeted game object. As long as that targeted game object remains on the board, that relationship is maintained even if the target no longer fulfills the targeting restrictions of the spell. Even if the units in this example aren’t at a battlefield anymore, they are still being chosen by Alpha Strike. We know this is true because the spell remembers that it is targeting those units if they happen to fulfill its targeting restrictions again per rule 359.3.e.3. The only exception to this principle is if the units change to a non-board zone—in such a case, they are no longer the same game object and any relationship between them and the spell that targets them is severed. Even if they returned to the same battlefield, they won’t be legal targets and the spell won’t be choosing them.
359.3.e.3.	If a target ceases to meet the targeting requirements while the spell is on the chain, then meets them again, it's a legal target.

It can help to visualize Alpha Strike’s targets with a colored arrow pointing from Alpha Strike to those units. Even if the units move to base and are no longer legal targets, they are still being chosen by Alpha Strike; we can imagine that the arrow is greyed out, but still present. Meanwhile, if they moved to a non-board zone the arrow would disappear entirely, since the game object it is connected to no longer exists. Repulse cares about the number of those arrows that point to friendly units, not the color of the arrows.

If I hold Reckoner’s Arena with Yone, Blademaster, will I place his triggered ability on the chain when the hold effect of Reckoner’s Arena resolves?

No, you will not. The main thing you need to know is that activating a conquer effect such as the Reckoner’s Arena effect is the equivalent of checking the condition of all of the specified conquer effects, as if a conquer had occurred at Reckoner’s Arena. Any triggered abilities of units at Reckoner’s Arena that trigger on conquering will see a conquer event occurring, but they will still need to check their other conditions in order to go on the chain. 

In this case, the rest of Yone’s conquer effect condition is “...that was previously uncontrolled,” and since the battlefield wasn’t previously uncontrolled, Yone’s ability will not trigger. 

Note that no actual conquer occurs—we’re simply treating the game as if a conquer had occurred at that battlefield for the purposes of the specified abilities. In Reckoner’s Arena’s case it specifies units, so only units with conquer effects at Reckoner’s Arena will see this conquer event and potentially trigger.

(We recognize the rules for “activate” in the way discussed above are underdefined. Expect further revisions in the next rules update.)

What happens if I play Atakhan from my deck with Rek’Sai, Breacher on the board? Can I pay the Accelerate cost and kill Rek’Sai for the Atakhan additional cost? Will it enter ready?

Yes, as long as you pay the Accelerate cost, Atakhan will enter ready, even if he kills Rek’Sai for his additional cost. This is because Accelerate creates a delayed replacement effect that causes Atakhan to enter ready. Although he lacks the Accelerate keyword when he resolves, he still has the delayed replacement effect that Accelerate generates.

How does HOT FEPR actually work?

HOT FEPR stands for Handle Outstanding Tasks; then Finalize, Execute, Pass, Resolve. Outstanding Tasks include the various procedures of the turn: things like readying all of your game objects on the board in the Awakening Phase, scoring battlefields in the Beginning Phase, drawing 1 in the Draw Phase, the steps of a cleanup, and the substeps of the Combat Phase, among other procedures. Each of these tasks is made outstanding when a player is expected to perform them, and a player must handle any outstanding tasks before proceeding to the next substep, step, phase, or turn.

FEPR is the process by which items on the chain are processed. Finalizing an item on the chain involves making choices, paying costs, and checking legality. Executing items to the chain means a player adding an item to the chain when they have priority, or passing priority. When all players Pass priority in a row, the topmost finalized item on the chain Resolves. While there are tasks outstanding, the FEPR process will be paused in place until all tasks are handled. 

An initial question many players are going to have is why add this system at all? Wasn’t FEPR good enough on its own? The reason we implemented the HOT part of HOT FEPR is that prior to this system, the game only had one rule to address how and when items on the chain interact with the procedures of the game: what is now rule 305. It says “when there are no items on the chain and the turn player cannot or chooses not to perform any discretionary actions, the current phase or step of the turn ends and the next phase, step, or turn begins.” 

FEPR was a great starting point, but there were several places that were unclear about how it functioned. Primarily, for our purposes, how we approached the sub-rules of a given step. Do we pause to FEPR items between each sub-rule and procedure? Or between several procedures? We realized that it needed more clarity.

HOT FEPR as a system tells us precisely when the FEPR process can occur during the turn and when it is precluded from occurring. While tasks are outstanding, pause FEPR and handle those tasks. Once all outstanding tasks are handled, any items on the chain undergo the FEPR process. Then when there are no more items on the chain and no outstanding tasks, we can move to the next procedure of the turn, per rule 335.3.
335.3.	If there are no outstanding tasks, no pending Chain Items, and it is the Main Phase, the turn player receives priority. If there are no outstanding tasks, no pending items, and it is any other phase of the turn, proceed to the next substep, step, phase, or turn.

An important point that is easy to miss in the HOT FEPR system is that it is recursive, that is the procedures which designate tasks as outstanding are themselves steps or substeps. Anytime the Core Rules Document says “the following task(s) become outstanding,” that step itself waits until any outstanding tasks and any items on the chain are completed. This will hopefully help make sense of the various procedures where HOT FEPR orders the turn. 

Let’s look at two examples to illustrate this:

The Resolution Step of Combat can be broken down into four subsections: 

    The Combat Cleanup
    Determine Combat Result
    Establish Control
    Combat Ends

As we move between each of these subsections, there will be a window to perform the FEPR process on chain items, and only after the chain is empty and there are no outstanding tasks, would we proceed to the next subsection.

The second example is that cleanups work in the inverse, where several tasks are queued at once and all must be completed before the FEPR process will initiate.
305.	When there are no items on the Chain and the Turn Player cannot or chooses not to perform any Discretionary Actions, the current phase or step of the turn ends and the next phase, step, or turn begins.

