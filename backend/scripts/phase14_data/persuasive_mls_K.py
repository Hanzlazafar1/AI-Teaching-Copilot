"""Kindergarten persuasive MLs — hand-composed entries.

Each entry preserves Smekens' verbatim teacher language (copied from the
source PDF), but rearranged from the PDF's 4-column grid layout into the
canonical STEP 1 → 2A → 2B → 3 → 4 reading order that downstream SCRIPTED_ML
retrieval + generation expects.

Source: `K MLs. Persuasive.pdf` (Smekens Education Solutions, © 2017).
Four MLs per file: SKILL #1, SKILL #2 day 1, SKILL #2 day 2, SKILL #3.

WRITING-TRAIT RATIONALE:
  * SKILL #1 "Recognize opinion topics" → Ideas (content-category
    recognition; identifying what an opinion IS vs a fact — a thinking
    skill, not a structural one).
  * SKILL #2 "Determine the strongest side" (both days) → Ideas
    (evaluating which content has the most support; selecting strongest
    argument — Ideas cluster: generating + filtering ideas).
  * SKILL #3 "Write an opinion" → Organization (it's the lead/introduction
    sentence. Matches Launch 3-12 Section 9 (Organization) precedent,
    where "persuasive-argumentative-introductions" lives.)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# SKILL #1 — Recognize opinion topics (K)
# ---------------------------------------------------------------------------

ML_K_SKILL_1 = {
    "grade": "K",
    "ml_number": 1,
    "day_number": None,
    "skill_title": "Recognize opinion topics",
    "writing_trait": "Ideas",
    "source_pdf": "K MLs. Persuasive.pdf",
    "source_page": 1,
    "lesson_triggers": [],

    # Canonical step-sequenced content (composed from the PDF's grid layout).
    # Preserves Smekens' teacher-voice wording; only the ordering is rebuilt.
    "content": """\
PERSUASIVE WRITING SKILL #1: Recognize opinion topics — Kindergarten

STEP 1 (Introduce — I do; you watch & listen):
We know that writers share stories and teach information. But writers can also share what they think or believe. Today, I'm going to teach you how to tell when writing is sharing an opinion — or not.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is | Persuasive writing starts with an opinion. An opinion tells what the writer thinks, feels, or believes about a topic that has different sides or choices. Facts are right or wrong — but opinions are not. They are simply different. People can think and feel differently about the same topic. (Introduce the icons & hand gestures.)

When a reader recognizes that a piece of writing is persuasive, he understands: the writer is going to share what HE thinks and explain why his choice is best.

WHY the skill is important | If a reader cannot tell the difference between opinions and facts, he may confuse the writer's opinion with true information. When readers recognize persuasive writing, they understand: "This is what the author believes." Then they can read and decide whether or not to agree.

HOW the skill works | After reading a little bit of the text…
1. ASK: Is the author describing what happened to characters? If yes, then it's a narrative story.
2. ASK: Is the author teaching facts everyone agrees on? If yes, then it's informative writing.
3. ASK: Is the author sharing his thoughts and feelings on a topic? Look for opinion words like "I think, my favorite, the best." Ask yourself: Could someone have a different opinion on this same topic? If yes, then it's persuasive writing.

This is how readers determine if a writer is revealing a story, telling facts, or sharing his opinion.

STEP 2B (Show the children — 5 minutes):
Let me show you how I figure out what type of writing this is. Project Lunch Text A and quickly read it aloud to yourself. Do not ask students to comment.
1. Ask: Is the author describing what happened to characters? (Scan the text.) I don't see a main character. Nothing is happening to anyone. This is NOT a narrative.
2. Ask: Is the author teaching facts everyone agrees on? (Point to individual sentences.) "Lunch is a time to eat during the school day." That's a fact. "Lunch gives your body energy." Everyone agrees with that. Hmm… Everything here sounds like true information. But let me check one more question before I decide.
3. Ask: Is the author sharing his thoughts and feelings about a topic? Let me look for opinion words like — I think, I feel, the best. (Scan slowly, pointing.) I don't see any. The author is simply describing lunch. Shake head. This is NOT persuasive.
So it's definitely not a story or an opinion. This text includes facts everyone agrees on. This is informative writing.

OK, I'm going to do this again. I'm going to determine if the author is sharing an opinion with me/the reader. Project Lunch Text B and quickly read it aloud to yourself. Do not ask students to comment.
1. Ask: Is the author describing what happened to characters? (Scan the text.) I don't see a character or a problem. Nothing is happening to anyone. This is NOT a narrative.
2. Ask: Is the author teaching facts everyone agrees on? (Point to individual sentences.) "You get to eat yummy food." Hmm — is "yummy" a fact? Not everyone thinks the same food is yummy. (Pause.) "After lunch you feel ready to learn." That seems like a fact — but I also know I sometimes feel sleepy after eating a big lunch. Hmm… I'm not sure. Let me check the third writing purpose.
3. Ask: Is the author sharing his thoughts and feelings about a topic? Let me look for opinion words. (Point to the very first sentence.) "I think lunch is the best time at school." There it is — "I think." That is an opinion phrase and "best" is a sign this is a persuasive writing. The author is telling me what HE thinks, not what everyone agrees on. Someone could have a different opinion. Someone might think recess or art is the best time of the day. (Nod.) Since I can name a different opinion, this topic is definitely NOT informative. This is persuasive writing. The author is sharing what he thinks and trying to get me to agree.

Today, we are learning how to recognize the signals that reveal if an author is sharing his opinion — if he is writing persuasively.

STEP 3 (Interact — We do; I do again, you help me):
Help me with another example. Project Family Text A. Read it aloud quickly. Do not ask students to comment.

Ask: Is the author describing what happened to characters? Turn & Talk. (Eavesdrop for 6–10 seconds.) Back to me. I heard many of you say that you don't think it is… but then again "family" could be the character and "feeling sad" could be a problem. Hmm… let's move on to the next writing purpose and see if it helps us.

Reread "My family is very special to me" and "We have so much fun playing games and laughing." 2. Ask: Is the author teaching facts everyone agrees on? Do all families play games or is this author sharing about HIS family? Turn & Talk. (Eavesdrop for 6–10 seconds.) Back to me. I heard many of you say it's not true for everyone. Let's look at another sentence. "Families are the best." Do you see any opinion words in that sentence? Turn & Talk. (Eavesdrop for 6–10 seconds.) Back to me. I heard many of you say "best." So what type of writing is this? 1… 2… 3… Blurt! Persuasive — right!

STEP 4 (Close — You do; I help):
Writers, today we learned how to tell when a writer is sharing his opinion — or not. If we can recognize opinions, then we are closer to being able to write them.

During Independent Writing Time, your job is to read several short texts and apply the same process. You will mark the text with a "P" if you determine it's persuasive and shares an opinion. Mark an "I" if it's informative and teaches facts. Mark an "E" if it's an entertaining narrative story. Let's go be writers!
""",

    "hyde_summaries": [
        "How do I teach kindergarteners to recognize opinion writing vs. informative or narrative?",
        "Mini-lesson on telling the difference between opinions and facts for K",
        "K lesson on identifying persuasive writing using the three writing purposes",
        "How do I help K students spot opinion words like 'I think' and 'the best'?",
        "Scripted mini-lesson for kindergarten on recognizing opinion topics",
        "Lesson on distinguishing narrative, informative, and persuasive writing for kindergarteners",
        "Give me a K persuasive writing lesson on what makes writing an opinion",
    ],
}


# ---------------------------------------------------------------------------
# SKILL #2 day 1 — Determine the strongest side (1 of 2) (K)
# ---------------------------------------------------------------------------

ML_K_SKILL_2_DAY_1 = {
    "grade": "K",
    "ml_number": 2,
    "day_number": 1,
    "skill_title": "Determine the strongest side",
    "writing_trait": "Ideas",
    "source_pdf": "K MLs. Persuasive.pdf",
    "source_page": 2,
    "lesson_triggers": ["blue-hat-red-hat", "hand-over-mouth"],

    "content": """\
PERSUASIVE WRITING SKILL #2: Determine the strongest side (1 of 2) — Kindergarten

STEP 1 (Introduce — I do; you watch & listen):
We know that persuasive writing is about choices — it's about picking a side and writing about what you think. But how do you pick which side to write about? Today, I'm going to teach you how to determine which side is the strongest.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is | Persuasive writing is more than just your opinion — it's the strongest opinion that you can prove. Writers don't "pick" a side right away. First they think carefully about both choices.

WHY the skill is important | The strongest side is the one you can say the most about. If you pick a side too fast, you might miss a stronger one. Thinking through both sides first helps you find the one with the most to say.

HOW the skill works |
Step 1: Name both sides. Look at your topic. What are the two choices? Don't pick yet — just name them.

Step 2: Hand over mouth. It's hard not to blurt out your favorite right away. (Demonstrate hand over your mouth.) We slow down and think first.

Step 3: Think like one side. (Reveal the blue hat.) Writers put on the thinking cap of someone who believes this side is best — even if your heart isn't there. (Teach students to use their hands and mime placing a hat on their heads.) When you've thought of everything you can for that side, take the hat off. Stop thinking like that person.

Step 4: Think like the other side. (Reveal the red hat but don't put it on yet.) You may have enjoyed thinking about the first side — but this one? Maybe not so much. But we have to pretend to love this side. We don't say "eww" or make faces. So you put on that hat and think their thoughts. (Introduce the gesture of picking up a hat, putting it on, thinking, taking it off, then switching to the other hat.)

Ask yourself: What is good about it? What would someone who loves this side say? Thinking like the other side is hard. Here are a couple writer tricks to help you.
• Close your eyes and picture a person — maybe someone you know — who would really love this choice. What do they like? Why would someone choose this? What would they say is good about it?
• Have you ever seen this topic/side in real life? A place, a person, a thing? What did you notice? That might help you think of more details that make someone like this.
• What have you heard about this topic/side? What have your friends, family, or teachers said about this?

Remember, you are only pretending to like this side. You're just borrowing that person's brain for a minute. Only after thinking through both sides carefully can a writer determine which one is stronger.

STEP 2B (Show the children — 5 minutes):
Let me show you how I think through both sides before I pick one.

Step 1: Name both sides. My topic is: Which is the better fast food restaurant — McDonald's or Taco Bell? (Display the McDonald's & Taco Bell T-Chart.) Those are my two choices. I'm not picking yet. I'm just naming them.

Step 2: Hand over mouth. My first thought is already in my head — but I'm not saying it yet. (Place hand over mouth.) I have to think through both sides first.

Step 3: Think like one side. (Place the blue hat on your head.) I'm putting on my McDonald's thinking cap. I'm going to think like someone who really loves McDonald's — (whisper) which isn't hard because I really do love it. OH NO! (Slap hand over mouth.) OK… So I have to think of things great about McDonald's. It has those crispy fries. And Happy Meals with toys. And Playland where kids can run around. And McFlurries! And chicken nuggets. And breakfast all day. Wow! It's so easy to think of details when I love the choice. OK, I've thought of everything I can for this side. (Take the hat off.) I'm done thinking like a McDonald's person.

Step 4: Think like the other side. (Hold up the red hat but don't put it on yet.) Now I have to think like someone who loves Taco Bell. Hmm. (Make a neutral face — no "eww," no faces.) I don't really know much about Taco Bell. I haven't been there much. But I have to pretend to borrow someone else's brain. (Put on the red hat.) Let me close my eyes and picture those Taco Bell commercials — the ones with people biting into crunchy tacos piled high with toppings… who love that you can choose hard or soft shells… who gets excited about all the different sauces… who likes that Taco Bell feels different from every other fast food place — like it's got its own thing going on. (Lift hat slightly off your head and whisper.) I don't really like all that stuff, (put hat back on head), but someone who loves Taco Bell probably does. And that's what I'm doing, trying to think like someone who loves this choice.

Today, we are learning how to think through both sides of a persuasive topic so that we can eventually figure out the strongest side.

STEP 3 (Interact — We do; I do again, you help me):
Help me with another example.
1. Name both sides. The topic is: What is the best season — summer or winter? (Display both sides. Point to each.) Two choices. We are not picking yet — just naming them.
2. Hand over mouth. You may already have a favorite but don't say it! (Hand over mouth.) We have to think through both sides first.
3. Think like one side. (Blue hat on — students mime.) Summer thinking cap. What details come to mind for someone who loves summer? Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. I heard hot sunny days, swimming, ice cream, popsicles, no school. So many details! (Hat off — students mime.) OK, we've thought of many summer-is-the-best details.
4. Think like the other side. Now we have to think like someone who loves winter — even if you don't. (Red hat on — students mime.) Let's close our eyes and picture someone playing outside in winter. Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. I heard building a snowman, snowball fights, hot chocolate. What else is fun or good about winter? What events or holidays occur over the winter? Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. I heard go sledding, Christmas time, etc.

STEP 4 (Close — You do; I help):
Writers, today we learned how to think through both sides of a persuasive topic before picking one.

During Independent Writing Time, you and your partner will think through which is better — indoor or outdoor recess. When I project a topic, put on your blue hat and together I want you & your partner to think every detail you can for that side. Then switch pretend hats and think like someone who loves the other side. See how many details you & your partner can come up with for each side. Let's go be writers!
""",

    "hyde_summaries": [
        "How do I teach kindergarteners to weigh both sides of a persuasive topic before picking one?",
        "Mini-lesson on the blue hat / red hat thinking routine for K persuasive writing",
        "K lesson on choosing the strongest side for a persuasive piece",
        "Scripted ML for kindergarten on thinking through both sides of an opinion",
        "How do I get K students to hold back their opinion and consider the other side?",
        "Lesson on persuasive prewriting — thinking like each side before choosing",
        "Give me a K persuasive lesson on the hand-over-mouth / thinking-cap strategy",
    ],
}


# ---------------------------------------------------------------------------
# SKILL #2 day 2 — Determine the strongest side (2 of 2) (K)
# ---------------------------------------------------------------------------

ML_K_SKILL_2_DAY_2 = {
    "grade": "K",
    "ml_number": 2,
    "day_number": 2,
    "skill_title": "Determine the strongest side",
    "writing_trait": "Ideas",
    "source_pdf": "K MLs. Persuasive.pdf",
    "source_page": 3,
    "lesson_triggers": ["two-perspectives-t-chart", "blue-hat-red-hat"],

    "content": """\
PERSUASIVE WRITING SKILL #2: Determine the strongest side (2 of 2) — Kindergarten

STEP 1 (Introduce — I do; you watch & listen):
Yesterday we learned how to think through both sides of a persuasive topic — putting on each thinking cap and pushing ourselves to think of small, specific details for both sides. Today I'm going to teach you how to jot down the details you think of for each side. This will bring us one step closer to determining the strongest side.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is | Yesterday we thought about both sides of a persuasive topic. But thinking alone isn't enough — if writers only think through details in their heads, those ideas slip away before they ever make it into writing.

Jotting captures each detail on paper during prewriting. Jotting means writing something down quickly and simply — just enough to remember the thinking. Kindergartners jot with a quick picture and a label word — not a detailed drawing. (Connect to research unit jotting if previously taught — SKILL 1, Days 2-3.) We used jotting before when we were doing research & collecting fact phrases from texts.

WHY the skill is important | If writers only think through details in their heads, ideas slip away. Jotting captures each detail on paper so it doesn't get lost.

HOW the skill works |
Step 1: Name both sides. Write one choice at the top of each side of the T-Chart. Write one choice next to the blue hat and one choice next to the red hat.

Step 2: Hand over mouth. Resist blurting out an opinion. We are going to THINK about both sides, one at a time.

Step 3: Think like one side & jot. (Reveal the blue hat.) Remember to put on the thinking cap of someone who believes this side is best. (Students mime placing a hat on their heads.) As you think of a detail, jot it in its own space on that side of the T-Chart. Writers put a quick picture and simple label to remind them of the detail they thought of. Then, when you think of another detail for that same side, write it below the one before it, stacking down that same side. All of the details for that one choice are on the same side.

If you fill up all the spaces on that side — don't stop and don't switch to the other side yet. Grab a second T-Chart and keep jotting on that same side. The other side stays empty for now — that's OK. You are still thinking like a blue hat person. Stay in that thinking cap until every detail is captured. (Remove blue hat. Students mime.)

Step 4: Think like the other side & jot. (Put on the red hat. Students mime.) Now think like someone who loves the OTHER choice. Use the same thinking strategies. Say each detail out loud. Then jot it (quick picture & word label) in its own space on that side of the T-Chart.

STEP 2B (Show the children — 5 minutes):
Let me show you how I jot details for both sides of my persuasive topic.

Step 1: Name both sides. Yesterday my topic was: Which is the better fast food restaurant — McDonald's or Taco Bell? (Display a blank T-Chart.) The first thing I have to do is write one choice at the top of each side. (Write McDonald's on the left. Write Taco Bell on the right.) There — both sides named.

Step 2: Hand over mouth. I already know which one I love — (hand over mouth) — but I'm jotting both sides first because that's what persuasive writers do.

Step 3: Think like one side & jot. (Place the blue hat on your head.) I've got my McDonald's thinking cap on. Yesterday I thought of several details that make McDonald's great. I need to rethink of them, one at a time, and jot them on the McDonald's side of the T-Chart.
• Crispy fries is a detail. (Draw while talking aloud.) I can draw a quick picture of fries using my pencil. I need to put it in the first box under the McDonald's side. And I'll label it "fries."
• (Look up and think.) I'm also thinking that McDonald's is great because of the Happy Meal. (Look down at the first detail and slide your finger to the next space below it.) I need to write this next McDonald's detail in the space below the first one. I have to keep all the McDonald's details on the same side. (Draw while talking aloud.) I can draw a box with a handle on it. I'll label it "Hap Meal." That's my jot. It's just a reminder of a detail I'll write in a sentence later.
• (Repeat with McFlurry. After the third detail, demonstrate what to do when one side is full.) Wow — I filled up this whole side! But wait — I just thought of something else — the Playland at McDonald's. (Look at the full T-Chart.) There are no more spaces on this side. Do I stop? No! I grab a second T-Chart. (Display a second T-Chart.) I write McDonald's at the top of this side too — because I'm still thinking like a McDonald's person. (Model drawing and labeling Playland.) OK, I've thought of everything I can for this side. (Take the hat off.) I'm done thinking like a McDonald's person.

Step 4: Think like the other side & jot. (Put on the red hat.) I put on the thinking cap of someone who loves Taco Bell. (Point at T-Chart and the right side.) Any details I come up with now, will all go on the right side — under the words "Taco Bell." I'm picturing someone who loves crunchy tacos piled high with toppings.
• Draw a taco and write "taco."
• Draw a curved hard shell and a circle/soft shell. Write "shells."
• Draw a rectangle and label it "sauces."

Today, we are learning how to think & jot details for both sides of a persuasive topic. This is what writers do before determining the strongest side.

STEP 3 (Interact — We do; I do again, you help me):
Yesterday, you thought about: What is the best season — Summer or Winter? Help me jot down those details. (Reveal a new T-Chart.)

1. Name both sides. Where should I write "Summer?" Point in the air. Yes, right here next to the blue hat. And where do I write down the other choice — winter? Point in the air. Yep, right here by the red hat.

2. Hand over mouth.

3. Think like one side. (Blue hat on — students mime.) Guide students to think, Turn & Talk, and help you jot one detail at a time — swimming, ice cream, popsicles, no school. (Model how to start a second T-Chart when one side gets full.)

4. Think like the other side. (Switch hats.) Guide students to think, Turn & Talk, and help you jot one detail at a time — building a snowman, snowball fights, hot chocolate, sledding.

STEP 4 (Close — You do; I help):
Writers, today we learned how to think & jot down details for BOTH sides of a persuasive. This is an important step before we can determine the strongest side.

During Independent Writing Time, you will fill out a T-Chart for which is better — indoor or outdoor recess. This time you will work alone. (Yesterday you brainstormed with a partner. Today, you will jot down the details by yourself.) Think of all the details you can for one side before switching to the other side. And if you need a second T-Chart, I've got extra ones right here. Let's go be writers!
""",

    "hyde_summaries": [
        "How do I teach K students to jot details for both sides of a persuasive topic on a T-Chart?",
        "Mini-lesson on capturing persuasive details with quick pictures and word labels for K",
        "K lesson on filling out a T-Chart while thinking like each side of an opinion",
        "Scripted ML for kindergarten on the second day of determining the strongest side",
        "How do I get K writers to jot evidence for both sides before picking one?",
        "Lesson on persuasive prewriting — writing down details for the blue hat and red hat sides",
        "Give me a K persuasive writing lesson on using a T-Chart to capture ideas",
    ],
}


# ---------------------------------------------------------------------------
# SKILL #3 — Write an opinion (K)
# ---------------------------------------------------------------------------

ML_K_SKILL_3 = {
    "grade": "K",
    "ml_number": 3,
    "day_number": None,
    "skill_title": "Write an opinion",
    "writing_trait": "Organization",
    "source_pdf": "K MLs. Persuasive.pdf",
    "source_page": 4,
    "lesson_triggers": ["train-engine-caboose", "opinion-words-anchor-chart"],

    "content": """\
PERSUASIVE WRITING SKILL #3: Write an opinion — Kindergarten

STEP 1 (Introduce — I do; you watch & listen):
Up until now, everything we have done in our persuasive unit has fallen under prewriting. We've listed details for both sides and figured out the strongest one. Now it's time to start drafting — and the very first thing a persuasive writer does is tell the audience his opinion. Today, I'm going to teach you how to write out the opinion at the beginning of any persuasive writing.

STEP 2A (Tell the children — 5 minutes):
All writing has a beginning, middle, and end — like a train with an engine, middle cars, and a caboose. That's a complete train and complete writing.

WHAT the skill is | In persuasive writing, the engine is the opinion sentence. This is where the writer tells the reader which side he chose and what he thinks.

WHY the skill is important | The reader needs to know right away that the writer is sharing an opinion. Starting with an opinion sentence tells the reader: this is what I think. Without an opinion sentence at the beginning of persuasive, the reader doesn't know what side the writer is on.

HOW the skill works |
STEP 1. Name the strongest side. Look back at your T-Chart. Find the side circled. Find the word(s) written next to the hat (on the strongest side). Use that word or those words in the first sentence.

STEP 2. Choose 3 opinion words/phrases. (Connect to SKILL #1 — opinion signal words.) These words signal to the reader that an opinion is coming. Choose 3 to test out in Step 3.

STEP 3. Put the two parts together. Say it in one sentence out loud: strongest side + opinion words. Name the strongest side AND one of the opinion words/phrases in one sentence.
• Then, say the strongest side again with a different opinion word/phrase.
• Try out a couple different sentences by saying them out loud.
• You are sharing the same opinion each time; you're just saying it a little differently. So listen to the different ways you come up with. Pick the one that is easiest to say and easiest to understand.
• The one that sounds the best is the sentence to write/draw.

STEP 4. Write the sentence. After reading this first sentence, the audience will know exactly WHAT the writer thinks.

(NOTE: Stop there. The first sentence only names the opinion. No details. No "because.")

STEP 2B (Show the children — 5 minutes):
Let me show you how I write my opinion sentence.

STEP 1. Name the strongest side. I look back at my T-Chart. (Point to the T-Chart.) I circled this side — McDonald's. That was my strongest side. It had the most details, the most proof. (Point to the word "McDonald's" next to the blue hat.) That's the word I need in my first sentence.

STEP 2. Choose 3 opinion words or phrases. Now I need to pick 3 opinion words/phrases to try out. (Point to the opinion word anchor chart.) I'm going to try these — "My favorite…, I think…, I like…" (Write on the board.)

STEP 3. Put the two parts together. Now I put the two parts together — one of the opinion phrases plus "McDonald's," the strongest side. I'm going to try all three out loud and see which one sounds best.
• "My favorite…" + McDonald's. (Pause & think.) "My favorite fast food restaurant is McDonald's." Hmm. That sounds like a complete sentence. I like it — but let me try the next one.
• "I think…" + McDonald's. (Pause & think.) "I think McDonald's is the best fast food restaurant." Ooh — that sounds strong. And I used "best" — that's another opinion word. I'll try one more way to say my opinion.
• "I like…" + McDonald's. (Pause & think.) "I like McDonald's better than any other fast food restaurant." That's OK — but it doesn't feel as strong as the first two.

(Review the first two choices again, saying them to yourself out loud.) I think I like the second one best — "I think McDonald's is the best fast food restaurant." It sounds strong. It sounds like an opinion. And it tells my reader exactly which side I chose.

STEP 4. Write the sentence. So now I need to write my opinion. This will be my very first sentence on lined paper. (Write slowly while narrating: I… think… McDonald's… is… the… best… fast… food… restaurant.) (Put the pencil/marker down.) And I stop. Right there. No because. No details. My reader knows what I think. The beginning is just my opinion.

Today, we are learning how to use our T-Charts and opinion words to write the beginning sentence of any persuasive writing.

STEP 3 (Interact — We do; I do again, you help me):
Help me with another example. (Reveal the T-Chart of best season — summer or winter?)

1. Name the strongest side. Which side did we determine was the strongest yesterday? Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. Yes, summer! How do you know? Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. Right, because it has the most details. So we want to use the word "summer" in our opinion sentence.

2. Choose 3 opinion words/phrases. Look at the anchor chart. We also need to choose some opinion words from the chart. How about: "My favorite…, I think…, The best…"

3. Put the two parts together. Now it's time to put those two parts together — "summer" and "My favorite." Let's try each one out loud. Which one sounds strongest?
• "My favorite…" + Summer. Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. I heard "My favorite season is summer."
• "I think…" + Summer. Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. I heard "I think summer is the best season."
• "The best…" + Summer. Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. I heard "The best season is summer."

Turn & Talk. (Eavesdrop 6–10 seconds.) Back to me. I agree, "I think summer is the best season" is a clear opinion. That's the first sentence to write in your persuasive.

Today, we are learning how to use opinion words and our strongest side from the T-Chart to write the first sentence of our persuasive piece.

STEP 4 (Close — You do; I help):
During Independent Writing Time, you will get out your T-Chart on which is better — indoor or outdoor recess? I want you to follow the same process that I just taught you: 1. Name the strongest side. 2. Choose 3 opinion words. 3. Put the parts together. I want you to write 3 opinion sentences — each one using a different opinion word with the strongest side. Let's go be writers!
""",

    "hyde_summaries": [
        "How do I teach kindergarteners to write a clear opinion sentence at the start of a persuasive?",
        "Mini-lesson on writing the opinion sentence for K persuasive writing",
        "K lesson on combining the strongest side with opinion words like 'I think' and 'my favorite'",
        "Scripted ML for kindergarten on writing a persuasive lead / introduction",
        "How do I teach K students to draft the first sentence of a persuasive piece?",
        "Lesson on the train-engine metaphor for the opening of persuasive writing",
        "Give me a K persuasive writing lesson on writing a one-sentence opinion",
    ],
}


ALL_K_MLS = [ML_K_SKILL_1, ML_K_SKILL_2_DAY_1, ML_K_SKILL_2_DAY_2, ML_K_SKILL_3]
