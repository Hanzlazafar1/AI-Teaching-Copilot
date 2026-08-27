"""Drawing, Labeling, Early Sentences MLs — hand-composed entries.

Source: `Drawing, Labeling, Early Sentences mini-lessons.pdf`
(Smekens Education Solutions). Targets EARLY WRITER content — students who
are "writing in pictures before writing in lots of words." All content
rearranged into the canonical STEP 1 → 2A → 2B → 3 → 4 structure, even
when the source PDF used flowing narrative (pages 1-3, 5) vs. the compact
grid format (pages 4, 6, 7).

7 MLs total. Grade markers as they appear in the source:
  * PK-1 (MLs 1-5, 7 — most of the book)
  * K (ML 6 — "Choose the BEST Adjective" marks "K" in the grid header)

Trait assignments:
  * Ideas — MLs 1, 2, 3, 4, 5, 7 (accuracy of information, detail, development)
  * Word Choice — ML 6 (best adjective selection)

OVERLAP WITH EXISTING LIBRARY: several skill titles already exist in the
K-2 library under different grade / developmental positioning:
  * "Magnify close-up picture details" → k2-s8-ml9-magnify-close-up-details
  * "Sticky-dot details" → k2-s13-ml3-sticky-dot-details
  * "True-to-life colors" → k2-s8-ml2-true-to-life-color-details
  * "Accurate sizes/shapes" → k2-s8-ml7-adjust-size-proportion-details

Per user decision, treat these as PK-1 SUPPLEMENTS — new library entries
with their own ml_ids (lib-pk1-*) and a `related_ml_id` cross-reference
to the K-2 original. Retrieval will surface the age-appropriate version
based on grade.

Originally all chunks carried ``lesson_trigger = ["early_writer"]`` per user's
chosen EARLY_WRITER marker (no new schema field). F66 canonicalization
(2026-07) dropped ``early_writer`` — not a canonical Smekens trigger token —
and remapped each ML's other near-miss tags onto canonical Phase-14 trigger
keys (see the `lesson_triggers` list on each ML below; some Task-1-added,
some pre-existing).
"""

from __future__ import annotations


ML_PK1_ACCURATE_SHAPES_SIZES = {
    "grade": "PK-1",
    "ml_number": 1,
    "day_number": None,
    "skill_title": "Teach your reader about a topic using accurate shapes and sizes",
    "writing_trait": "Ideas",
    "writing_mode": "Inform",
    "source_pdf": "Drawing, Labeling, Early Sentences mini-lessons.pdf",
    "source_page": 1,
    "lesson_triggers": ["shape-book"],
    "related_ml_id": "lib-k2-s8-ml7-adjust-size-proportion-details",

    "content": """\
PK-1 EARLY WRITER SKILL: Teach your reader about a topic using accurate shapes and sizes

STEP 1 (Introduce — I do; you watch & listen):
When we write, we can teach our reader about a topic by drawing pictures with accurate shapes. When we teach true things about a topic, it is called informative writing. Say informative writing with me. (Teacher and students repeat "Informative writing.") In today's lesson, I am going to show you how to draw accurate shapes about your topic for informative writing. This will help you with the trait of Ideas.

Writers, when we write informatively, we are teaching our reader true and accurate information about a topic. That means we cannot just guess. We cannot just write what we think we remember. Informative writers pull their information from what they have learned — from books they have read, articles they have studied, diagrams they have examined, and notes they have taken.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is: We already know how to draw topics by putting together several shapes... but now we want to emphasize the importance of drawing to teach true information. The picture must show the topic accurately. The sizes of the shapes must match real life. Big parts look big. Small parts look small. Accurate shapes help the picture clearly show the whole topic.

WHY this skill is important: If our sizes are wrong, our reader might misunderstand the topic. If the sizes are inaccurate, the reader may misunderstand what we are teaching. For example, a tiny house and a giant person might look like a dollhouse. A huge dog and a tiny person might look like a dinosaur. Accurate sizes help writers show truthful information. When writers draw the whole topic using correctly sized shapes, the picture becomes clearer. A clear picture helps the reader understand and learn from the writing.

HOW this skill works: Writers follow 3 steps to draw their topic accurately:
1. THINK about the object and the shapes inside it. Close your eyes and visualize the shapes inside it — round parts (made up of a circle or oval), long rectangular parts, and pointy triangular parts.
2. IDENTIFY the biggest shape in the object.
3. DRAW that shape on the paper… position it.

REPEAT the process, drawing the biggest shapes first, then medium shapes, and finally the smallest shapes. Teach the chant with hand motions: "Draw big things first, medium things second, and small things last."

Writers repeat these steps until the whole topic is clearly drawn.

STEP 2B (Show the children — 5 minutes):
Let me show you how to do this using a topic we have read about — animals. Reveal a photograph of a bear previously seen in subject-area reading. I'm not drawing yet — I'm thinking and looking. I remind myself that when we write informatively, our pictures are teaching. That means I can't just draw "something that looks like a bear." I have to draw the bear with accurate shapes and sizes so my reader learns true, real information about what a bear actually looks like. If I choose the wrong shape or make the body too tiny or the legs too long, then I'm not teaching correctly. So before I draw, I slow down and use my four steps.

Step 1: THINK — look closely and find the shapes hiding inside the object. I squint so the tiny details fade away and the bigger shapes pop out. I trace the imaginary shapes with my finger. I notice one big, round oval for the bear's belly and four short rectangles for the legs. I'm not tracing the outside outline of the bear — I'm finding the shapes inside the bear because those shapes will help me build it accurately.

Step 2: CHOOSE — decide which shape to draw first. I remember my rule: draw the biggest shape first. The biggest part of the bear is the belly, so I start with a big oval. But I also remind myself that "big" matters because I'm teaching the reader what the bear really looks like. A bear's belly is much bigger than its legs, so I need an oval that is large enough to match that truth. I find the right-sized oval in my Shape Book. If the first one is too small, I switch to a larger oval that matches the bear's body.

Now it's Step 3: SLIDE the Shape Book under my paper and position the oval in the correct spot. I'm thinking about accuracy again. I know the bear's body is the main part, and the legs will go underneath it, so I need to place the oval high enough to leave room below for four legs.

Step 4: TRACE. I trace slowly and carefully, staying on the line. There's my first shape — the bear's body. I check the photograph to make sure it matches, and it does.

Now I repeat the same four steps for the legs: 1. THINK (I already noticed four short rectangles), 2. CHOOSE (the short rectangle shape). If I choose a rectangle that is too long, my bear will look strange and I won't be teaching true information. So I choose short rectangles that match what I see. 3. SLIDE (place it under the oval because legs go under the body), and 4. TRACE (one leg at a time). I remind myself the bear has four legs, so I repeat the same shape in four spots. Then I step back — now it looks like a bear because I built it with accurate shapes and accurate sizes, one shape at a time, so my picture can teach the reader what a real bear truly looks like.

STEP 3 (Interact — We do; I do again, you help me):
Help me with the next one. This time, we will draw a house one accurate shape at a time. Reveal a photograph of a simple house.

Step 1: THINK while studying the photograph and trace the shapes in the air with a finger. Identify the shapes inside the house: square (base), triangle (roof), rectangle (door).

Step 2: CHOOSE the biggest shape first — the square base. Find a large square from the Shape Book that matches the photograph.

Step 3: SLIDE the Shape Book under the paper. Position the square low enough to leave room above for the roof.

Step 4: TRACE the square slowly and carefully.

Repeat the same 4 steps for each remaining part:
• roof — triangle on top of the square
• door — rectangle near the bottom of the square

STEP 4 (Close — You do; I help):
Writers, today we focused on drawing accurately because informative writing teaches true information. When we draw a topic, our shapes and sizes must match what is real. If our picture is inaccurate, we are not teaching our reader correctly. In informative writing, our job is to show the truth — what the topic actually looks like.

During Independent Writing Time, you will use your Mini-Shape Book to draw the photographs projected on the screen. Study each one carefully and apply the process you practiced today as you build each object. In each section of your quadrant paper, draw one whole object using 2-4 shapes, making sure the shapes and sizes accurately match the real photograph. Your picture must teach correct information. Let's go be writers.
""",

    "hyde_summaries": [
        "How do I teach PK-1 students to draw a topic with accurate shapes and sizes?",
        "Mini-lesson on using a Shape Book to build informative pictures for early writers",
        "Early-writer lesson on drawing big shapes first, then medium, then small",
        "How do I help PK-1 writers teach their reader through accurate drawings?",
        "Scripted mini-lesson for pre-K / kindergarten on drawing topics with correct shapes and sizes",
        "Lesson on the THINK-CHOOSE-SLIDE-TRACE process for early-writer informative drawings",
        "Give me a PK-1 lesson on drawing a topic so pictures teach truthful information",
    ],
}


ML_PK1_REAL_PEOPLE_DETAILS = {
    "grade": "PK-1",
    "ml_number": 2,
    "day_number": None,
    "skill_title": "Teach your reader about real people with accurate details",
    "writing_trait": "Ideas",
    "writing_mode": "Inform",
    "source_pdf": "Drawing, Labeling, Early Sentences mini-lessons.pdf",
    "source_page": 2,
    "lesson_triggers": ["biography", "basic-people-shapes"],
    "related_ml_id": None,

    "content": """\
PK-1 EARLY WRITER SKILL: Teach your reader about real people with accurate details

STEP 1 (Introduce — I do; you watch & listen):
Writers, we have been learning how to draw our topics accurately so our pictures can teach true information. Today, we are going to focus on drawing people — real people — in informative writing.

Sometimes we write to teach about a real person from the past or from today. When we write to teach about a real person and include lots of true information and details about who they were and what they did, that kind of informative writing is called a biography. A biography teaches the reader about a real person's life. Right now, because we are young writers, we begin our biographies with pictures before we write lots of words.

When we draw a real person in informative writing, our job is to teach true information about who they are and what they are known for. We already know how to draw a person using basic shapes — a circle for the head, a large rectangle for the torso, and four skinny rectangles for the arms and legs. We draw these lightly first. Every person starts with those same basic shapes. But today, we will learn how to turn that basic shape person into a specific, real individual by adding accurate colors, clothing, and accessories that teach exactly who they are.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is: Writers begin with the same basic people shapes drawn lightly. Then they add true-to-life color, clothing, and accessory details that are unique to that real person. These details help the reader recognize who the person is and what they are known for.

Every person has the same body parts — head, torso, arms, legs, eyes, nose, mouth, hands, and feet. If we stop there, our picture could be anyone. But informative writing is not about "anyone." It is about teaching our reader about a specific, real person. That means we must add details that are accurate and truthful.

Clothing and accessories are not decoration. They are information. Glasses might tell us someone wears them every day. A uniform might tell us what job they have. Special clothing might tell us what time period they lived in. Equipment or props might tell us what they are famous for. These details are facts.

WHY this skill is important: If we draw a person without accurate clothing, colors, or accessories, our reader may not understand who we are teaching about. If we give them the wrong details, we may teach incorrect information. In informative writing, we are responsible for teaching truth. That means our skin tones, hair color, eye color, clothing style, and important props must match real life.

HOW this skill works: Writers follow a careful process. First, lightly draw the basic people shapes. Second, zoom in and think about what makes this person unique — skin tone, hair, clothing, and what they are known for. Third, add accurate color and clothing shapes. Fourth, add simple accessory or prop shapes that help teach what they are famous for. Every added detail must match real life.

STEP 2B (Show the children — 5 minutes):
Let me show you how I do this with Ruby Bridges.

First, I lightly draw the basic shapes. Circle for the head. Large rectangle for the torso. Four skinny rectangles for the arms and legs. Small ovals for hands and feet. I add the close-up details we already know — eyes, nose, mouth — lightly.

Right now, this could be any child. That means I have not taught my reader anything specific yet.

Now I stop and think: I am writing informatively about Ruby Bridges. What true information must my picture show? What makes her recognizable?

I think about her skin tone. Ruby Bridges is an African American girl. That is true information. So I choose a realistic brown shade that matches her real skin tone. Not too light. Not random. I choose carefully because color communicates fact.

Next, I think about her hair. In photographs, Ruby wore her hair neatly styled. I add dark hair shapes around her head. I check myself: Does this match real photographs? Yes.

Now I think about clothing. Ruby Bridges is famous for going to school during segregation. I remember seeing photographs of her wearing a neat dress and carrying school materials. So I draw a simple dress shape over the torso rectangle. I choose realistic clothing colors — not neon green or purple — but colors that match photographs from that time.

Now I think about what she is known for. She is known for going to school bravely. So I add a small rectangular book shape in her hand. That book is not decoration. That book is information. It teaches what she is known for.

I step back and think: Does this picture teach true information about Ruby Bridges? Do the colors, clothing, and prop match real life? If yes, then my picture is informative.

STEP 3 (Interact — We do; I do again, you help me):
Now let's do this together with Martin Luther King Jr. First, we lightly draw the same basic shapes. Circle for the head. Large rectangle for the torso. Four skinny rectangles for the arms and legs. Close-up details for the face. Right now, he could be anyone.

Turn and tell a partner: What true-to-life skin tone should we choose? What hairstyle matches photographs? What clothing is he usually seen wearing? What might we add that helps teach what he is known for? (Turn & Talk.) Back to me. I heard many of you say he often wore a suit. That is accurate. So we add a suit shape over the torso rectangle. We choose realistic colors — black, gray, navy — colors that match photographs from real life.

We add dark hair and appropriate facial details based on real images. Then we think about what he is known for. He was a leader and speaker. So we can add a small rectangle shape in his hand to represent a speech paper. Or we could add a small microphone shape near his hand. Not because it looks cool — but because it teaches what he is known for.

We check ourselves again: Are these colors and clothing true-to-life? Does this picture teach correct information about MLK? If yes, then we are writing informatively.

STEP 4 (Close — You do; I help):
Writers, today we built on what we already know. Every person begins with the same basic shapes drawn lightly. But informative writing requires more than basic shapes. It requires accurate color, clothing, and accessory details that teach who that real person is and what they are known for.

If our details are wrong, we are not teaching truth. If our colors are random, we are not teaching accurately. In informative writing, our job is to show correct information about real people.

During Independent Writing Time, you will draw two more important people: Amelia Earhart and Abraham Lincoln. Begin with your light basic shapes. Then carefully add true-to-life skin tone, hair color, clothing shapes, and one simple prop that helps teach what they are known for. Amelia Earhart may include pilot clothing or goggles. Abraham Lincoln may include his tall hat or a formal suit jacket. Every added detail must match real life.
""",

    "hyde_summaries": [
        "How do I teach PK-1 students to draw a biography of a real person?",
        "Mini-lesson on adding accurate skin-tone, clothing, and prop details for early-writer biographies",
        "Early-writer lesson on turning a basic-shape person into a specific real individual",
        "How do I help PK-1 students teach about Ruby Bridges or MLK through informative drawing?",
        "Scripted mini-lesson for pre-K / kindergarten on drawing real people with accurate details",
        "Lesson on biography writing for young writers — pictures before many words",
        "Give me a PK-1 biography lesson on using clothing and props as factual information",
    ],
}


ML_PK1_TRUE_TO_LIFE_COLORS = {
    "grade": "PK-1",
    "ml_number": 3,
    "day_number": None,
    "skill_title": "Teach your reader about a topic using true-to-life colors",
    "writing_trait": "Ideas",
    "writing_mode": "Inform",
    "source_pdf": "Drawing, Labeling, Early Sentences mini-lessons.pdf",
    "source_page": 3,
    "lesson_triggers": ["true-to-life-colors"],
    "related_ml_id": "lib-k2-s8-ml2-true-to-life-color-details",

    "content": """\
PK-1 EARLY WRITER SKILL: Teach your reader about a topic using true-to-life colors

STEP 1 (Introduce — I do; you watch & listen):
Writers, we don't only write stories. Sometimes we write to teach information, and that is called informative writing. When we write informatively, we teach our reader true things about a topic. Right now, because we are young writers, we teach with pictures before we teach with lots of words.

We already know how to draw our topic using accurate shapes and correct sizes so our reader understands what we are teaching about. Today, I want to teach you how writers make their pictures even stronger by adding color details — and by choosing true-to-life colors so our picture teaches correct information. This strengthens the Trait of Ideas because color is not decoration. Color is information.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is: Writers add color details to their drawings and choose true-to-life colors so their picture teaches accurate information about the topic — the way it really is.

Color details are not just about making something pretty. Color communicates facts. The color of something tells the reader what kind of thing it is. A red apple and a green apple are both apples, but they are different kinds. A white bear and a brown bear are different animals. A yellow vehicle might tell the reader it is a school bus. Color gives specific information about the object itself.

WHY this skill is important: In informative writing, we are responsible for teaching truth. If we choose the wrong color, we may accidentally teach something incorrect. If I color a banana blue, my reader might wonder what kind of banana that is. If I color a brown bear white, I am no longer teaching about brown bears — I am teaching about a different animal.

Color also communicates condition. Is the apple ripe or not? Is the leaf healthy or dried out? Is the metal shiny or rusty? Those color choices are facts. They teach the reader something real. In informative writing, every color choice is information.

HOW this skill works: Writers ask themselves three important questions when adding color details.
First: What color is it mostly? That main color helps the reader recognize the topic.
Second: What smaller parts need different colors? Those smaller color details teach more specific information about the object.
Third: Are my colors true-to-life? Do they match how this object looks in real life? If not, I am not teaching accurately.

STEP 2B (Show the children — 5 minutes):
Let me show you how I do this. Yesterday we built this brown bear using accurate shapes and sizes so our picture could teach true information. Today I'm going to add color — but I have to think carefully, because this is informative writing.

First, I remind myself: My picture is teaching. My color choice is a fact. If I choose the wrong color, I could teach something incorrect.

I look at my bear. Before I grab a crayon, I ask myself the first question: What color is it mostly? I know I am teaching about a brown bear. That word "brown" is part of the information. So I cannot choose purple just because it's my favorite. That would not be truthful. I choose a brown crayon because that matches real life. (Begin coloring the large oval body and head brown.)

As I color, I'm thinking: This brown color is not decoration. It is classification. It tells my reader what kind of bear this is.

Now I ask the second question: What smaller parts need different colors? I look closely. The bear's nose is not brown. It is darker — almost black. If I leave it brown, I am leaving out information. So I choose black and carefully color the small oval nose. That small color change teaches a specific detail.

I also notice the teeth. Yesterday we added small triangles for sharp teeth. Teeth are not brown. If I color them brown, that would teach incorrect information. Teeth are light — almost white. So I leave them white. Leaving something white can also be a choice. That choice communicates truth.

Now I ask my third question: Are my colors true-to-life? I check myself. Brown fur. Dark nose. Light teeth. Yes. My color choices match what a real brown bear looks like. That means my picture is teaching accurate information.

STEP 3 (Interact — We do; I do again, you help me):
Now let's do this together with the house we drew yesterday. Before we pick up any crayons, we have to think like informative writers.

Turn and tell a partner: What color is the house mostly? What smaller parts need different colors? And what colors would be true-to-life so our picture teaches the truth? (Turn & Talk.) Back to me. I heard many of you say the house is mostly a light color — maybe white or tan. That makes sense. Houses are often painted neutral colors. So we will choose one main color and color the large square base first.

Now let's think about the roof. Is it the same color as the walls? Usually not. Roofs are often darker — gray, brown, maybe dark red. If we colored the roof bright pink, that might be possible somewhere, but it would not match this real photograph. So we choose a realistic roof color.

Now the door. Doors are sometimes a different color to stand out. We look at the photograph and match it. As we color, we keep asking: Does this match real life? Is this teaching correct information about this house?

Look at our house now. The colors help the reader learn what kind of house this is. The color differences between the roof, walls, and door give specific information.

STEP 4 (Close — You do; I help):
Writers, today you learned that in informative writing, color is not just for fun — it is for truth. Color details teach the reader more about the topic itself. True-to-life colors make your picture accurate — the way it really is. When you choose colors carefully, you are teaching correct information.

During Independent Writing Time, you will return to your four drawings — the tree, the school bus, the fish, and the sun. You already drew them with accurate shapes and sizes. Now your job is to add true-to-life color details so your pictures teach real information about each object. Before you color, think. Match the real object. Make sure your colors communicate truth.
""",

    "hyde_summaries": [
        "How do I teach PK-1 students to add true-to-life colors to their informative pictures?",
        "Mini-lesson on choosing colors as information (not decoration) for early writers",
        "Early-writer lesson on three color questions: what mostly, what smaller parts, is it true-to-life",
        "How do I help PK-1 writers see that color choice teaches classification?",
        "Scripted mini-lesson for pre-K / kindergarten on matching real-life colors in informative drawings",
        "Lesson on color as fact, not fun, for informative writing in early grades",
        "Give me a PK-1 lesson on picking the right color to teach the reader correctly",
    ],
}


ML_PK1_MAGNIFY_CLOSE_UP = {
    "grade": "PK-1",
    "ml_number": 4,
    "day_number": None,
    "skill_title": "Magnify close-up picture details",
    "writing_trait": "Ideas",
    "writing_mode": "Inform",
    "source_pdf": "Drawing, Labeling, Early Sentences mini-lessons.pdf",
    "source_page": 4,
    "lesson_triggers": ["magnify-close-up"],
    "related_ml_id": "lib-k2-s8-ml9-magnify-close-up-details",

    "content": """\
PK-1 EARLY WRITER SKILL: Magnify close-up picture details

STEP 1 (Introduce — I do; you watch & listen):
Writers, when we write to teach information (show informative icon), we tell true and correct things about a topic. Today I'll teach you how to share lots of small things about your topic. We'll learn how to add close-up details to our drawings. Close-up details help the reader learn more. And when we give MORE information, we grow the Trait of Ideas. (Show lightbulb.)

We already know we can write about a topic by drawing it using basic shapes and colors. But "basic" means plain or simple. That's a good start, but writers want to teach their readers A LOT. One way to do that is by adding close-up details to our pictures.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is | Close-up details are the little parts we add to basic shapes. These little parts are called details. Say "details."

WHY this skill is important | The more details we add, the more our reader learns. Close-up details help the reader see what the topic looks like and why it's special. That makes our writing clear, interesting, and informative.

(Show a magnifying glass.) A magnifying glass shows the tiny parts of something big. Those tiny parts are details. Writers zoom in on their own topics to find close-up details they could add.

Reveal "The Park" writing. Describe what the basic picture shows. Reveal the revision and show what new information is conveyed about the park from the close-up details included (e.g., it's an apple tree, the plane has stripes and windows, the swings have red seats and chains, the boy's fingernails are dark from playing in the dirt).

HOW this skill works | Writers add close-up details in 3 steps:
1. ZOOM IN: After drawing the basic shape(s) of the topic, the writer closes his eyes and "zooms in" on one area or part. Like a magnifying glass, he notices ONE close-up detail.
2. THINK: The writer opens his eyes and plans how to draw that small detail. He decides where to place it, what color to use, its size, and whether to use straight lines, swirls, or dots. The writer knows he is teaching the reader and wants to draw the detail correctly.
3. DRAW IT: The writer picks up his crayon or pencil and adds the close-up details as he imagined them.

After adding one close-up detail, the writer finds another part of the drawing and repeats the three steps.

STEP 2B (Show the children — 5 minutes):
Let me show you what these 3 steps look and sound like. We also know that when we write in pictures, we start with basic shapes and the right colors. Let's pretend I want to tell the reader about brown bears — a topic I know well. I used a brown crayon to draw an oval for the body, a circle for the head, and four skinny rectangles for legs.

Tape up the basic drawing and acknowledge it's a good start, but it's plain and has no close-up details. Tape up a photocopy of the same bear and that you will show them how you can add close-up details using the 3 steps.

1. ZOOM IN: I'm going to close my eyes and "zoom in" on one part of the bear — his face. I imagine a magnifying glass near his mouth. I notice something important: when a bear opens wide, it shows sharp, pointed teeth.
2. THINK: Open your eyes and think about how to draw the teeth correctly. I know I can't draw a smiley face because that's not true. I have to draw the teeth so they are pointed, so I am going to draw many small triangles.
3. DRAW IT: Now I'm going to draw the bear's mouth with small triangles to show that the bear has sharp teeth.

Even though I added one close-up detail, I'm not done. I need to find another part of the basic picture where I could add more information. Remember, I want to teach the reader everything I know about the topic, so I'm going to repeat the 3 steps again.

1. ZOOM IN: I'm going to close my eyes and "zoom in" on the bear's face again. I see the pointed teeth I just added, but I also imagine the bear's small, black eyes.
2. THINK: Now I will open my eyes and think about where and how to draw that. I know a bear's eyes are above his mouth, so it needs to be up here somewhere (point at the bear's face). And even though I really like blue eyes, I can't use the blue marker when writing about a bear. That's not telling correct information to the reader. If I want to teach my reader real information about brown bears, then I'm thinking I will use my black marker and color in two small circles here and here.
3. DRAW IT: Here I go; I'm drawing the brown bear's two small, beady black eyes.

Writers, look at my basic bear writing and compare it to this version with close-up details on the bear's face. Adding true, correct details helps me teach my reader more about the topic. That's one way to make my Trait of Ideas strong.

STEP 3 (Interact — We do; I do again, you help me):
Even though I've added TWO close-up details, I'm still not done. Help me find a third part of the bear to give more details about.

1. ZOOM IN: Close your eyes and zoom in on the bear's four legs. Look closely at his feet as if you had a magnifying glass. What do you see? Turn & Talk (e.g., paws, claws). Open your eyes. I heard several of you say you imagined paws or claws at the end of a bear's legs.

2. THINK: OK, now we have to do Step 2; we have to think about how to draw those close-up details. What shapes? How big? What color? Turn & Talk.

3. DRAW IT: I heard many of you say an oval for the paw and triangles for claws. I'll draw it here, and you draw it in the air with me.

STEP 4 (Close — You do; I help):
Writers, today we learned a 3-step process for how to add close-up details to our picture writing. By adding these little details, we can teach our readers even more about the topic we are writing.

For Independent Writing Time, I'd like you to draw a pumpkin. You will start with its basic shape and color, but then I want you to look for different places you can add close up details (e.g., texture of pumpkin skin, stem, dirty spot from where it grew on the ground). Let's go be writers!
""",

    "hyde_summaries": [
        "How do I teach PK-1 students to magnify close-up details in their informative pictures?",
        "Mini-lesson on the ZOOM-IN / THINK / DRAW-IT process for early writers",
        "Early-writer lesson on adding small details to teach more about a topic",
        "How do I help PK-1 writers use the magnifying-glass strategy to notice detail?",
        "Scripted mini-lesson for pre-K / kindergarten on the magnify close-up picture details skill",
        "Lesson on adding teeth, eyes, claws as close-up details to a basic bear drawing",
        "Give me a PK-1 lesson on zooming in to add informative close-up picture details",
    ],
}


ML_PK1_SETTING_ENVIRONMENT = {
    "grade": "PK-1",
    "ml_number": 5,
    "day_number": None,
    "skill_title": "Add setting and environment to teach where a topic belongs",
    "writing_trait": "Ideas",
    "writing_mode": "Inform",
    "source_pdf": "Drawing, Labeling, Early Sentences mini-lessons.pdf",
    "source_page": 5,
    "lesson_triggers": ["setting"],
    "related_ml_id": None,

    "content": """\
PK-1 EARLY WRITER SKILL: Add setting and environment to teach where a topic belongs

STEP 1 (Introduce — I do; you watch & listen):
Writers, you have already learned how to draw your topic clearly so it teaches true information. You learned how to build it with shapes, choose accurate sizes, and use true-to-life colors. Today I want to teach you how to make your picture even more informative by adding the setting or environment. In informative writing, we don't only teach WHAT the topic is — we also teach WHERE it belongs in the real world. When we add the setting, our reader understands the topic more fully, and that strengthens the Trait of Ideas because our picture teaches more true information.

STEP 2A (Tell the children — 5 minutes):
Writers, every real thing exists somewhere. People are in places like homes, schools, and workplaces. Animals live in habitats like forests, oceans, deserts, or icy land. Objects belong in real locations too — tools belong in a toolbox, a school bus belongs on a road, and a fish belongs in water. If we draw only the topic and nothing else, the reader can usually tell WHAT it is, but they may not learn WHERE it belongs. That's why informative writers add a setting: it teaches location information.

WHAT the skill is: Adding a setting means drawing parts of the place around the topic so the reader learns WHERE the topic is. Sometimes the setting also helps the reader understand WHEN it is happening, but our main job is to teach WHERE. A setting can include ground (what the topic stands on), a space around it (air, water, or indoor space), and a few place clues (like snow for an icy habitat, sand for a beach, or a classroom floor for school). We do not need to add a hundred things. We add just enough true information so the reader can tell where the topic belongs.

WHY this skill is important: The setting gives context. It helps the reader understand the topic correctly. A bear floating in empty space doesn't teach where bears live or what kind of place they move through. Ruby Bridges floating in empty space doesn't teach that she was a student going to school. The setting is not decoration — it is information. It helps the reader learn more about the topic without any words. And because this is informative writing, the setting must be true-to-life. If we put a fish in the sky or a school bus in the ocean, we would be teaching incorrect information.

HOW this skill works: Writers do three important things. First, they pause and pull on what they already know about the topic — what they learned from books, photos, and lessons — and ask, "Where does this belong?" Second, they decide what parts of the setting will teach that clearly. Some setting parts are big and simple and don't need the Shape Book — like grass, sand, snow, or water. Those can be broad strokes of color placed correctly so the topic is not floating. Other setting parts are specific objects that do need shapes — like a school building, a desk, a plane, a moon, or a sign — because those items must be recognizable and accurate. Third, writers place setting details correctly: under feet, behind the topic, or around it, using accurate sizes so the setting looks real and teaches true information.

STEP 2B (Show the children — 5 minutes):
Let me show you how I do this, using two topics we already drew. First I'm going to look at my brown bear. Right now, the bear is drawn clearly. The shapes are accurate. The colors are true-to-life. But the bear is floating on the page. My reader can tell WHAT it is, but they won't learn WHERE it belongs. So before I add anything, I stop and think, What do I know about bears from real photos and books? I know bears live on land, not in the sky. I picture the bear standing on the ground — dirt, rocks, or grass. If I put the bear on a bright pink floor, that would not teach true information. So the first setting clue I need is the ground under its feet. I choose a realistic ground color and I add it touching the bear's feet, because if it doesn't touch, the bear still looks like it's floating. I'm not scribbling all over the page; I'm placing the ground where it belongs so the picture teaches a real fact: bears stand on land. Now I think, Do I need a specific background object to teach where this bear lives, or is the ground enough? If I want to teach that this bear lives in the woods, I could add one or two trees in the background. Trees are made of shapes, so this is where the Shape Book could help. I keep the trees behind the bear and smaller than the bear so my reader understands they are farther away. Now my picture teaches more — this is a bear on land, in a wooded place.

Now I'm going to do the same thinking with Ruby Bridges. Ruby is drawn with accurate shapes, true-to-life colors, and clothing details. But right now, she is floating too. My reader can tell WHO she is, but the picture doesn't yet teach WHERE she is or what is happening. So I pause and pull on what I know about Ruby Bridges. Ruby was a student. She is famous for going to school. That means her setting should teach "school" without me writing a word. I ask myself, What is the simplest, most truthful way to show school? One way is to add a school building shape behind her — just a large rectangle with smaller rectangle windows and a door. That is specific enough that I want the Shape Book to help me make the building clear and accurate. I place the building behind Ruby, and I make it larger than Ruby only if it is close, or smaller if it is far away. I also add ground under her feet so she is standing, not floating. I choose true-to-life colors for the building — nothing wild — because I'm teaching. Now when a reader looks at my picture, they learn more true information: Ruby Bridges is a student at a school. The setting taught WHERE she is, which helps the reader understand her story in real life.

STEP 3 (Interact — We do; I do again, you help me):
Help me with the next one. Let's start with the house we drew yesterday. Right now, it's a clear house, but it is floating. Before we draw anything, think with your partner: where does a house belong? What should be under it so it looks real and teaches correct information? (Turn & Talk.) Back to me. I heard "ground" and "grass." Yes — houses sit on land. So we add ground under the house so it is resting in a real place. Now, should we add a specific object that helps teach "this is outside a house," or is the ground enough? (Turn & Talk.) Back to me. I heard ideas like a sidewalk or a mailbox. Those are specific objects, so we would use simple shapes to draw them, keeping them the right size and putting them in the correct place. We add just one or two so the reader learns WHERE the house is without clutter.

Now let's do MLK. We already drew MLK accurately as a person. But he is floating. Think with your partner: where might MLK be in real life when he is speaking and leading? What simple setting clue could teach that truth? (Turn & Talk.) Back to me. I heard "a stage," "a microphone," "a crowd," and "a building." For today, we're going to choose one clear setting clue that teaches WHERE he is. A microphone on a stand, or a podium shape, helps the reader understand he is speaking in a real place. Those are specific objects, so we use shapes to draw them clearly, and we place them correctly so nothing floats. We keep our colors realistic because this is informative writing and our goal is to teach true information.

STEP 4 (Close — You do; I help):
Writers, today you learned that in informative writing, our topic should not float alone. We add setting or environment details to teach WHERE the topic belongs in the real world. The setting is not decoration — it is information. It helps the reader learn more true facts about the topic by showing where it exists. And we have to keep the setting accurate, using true-to-life colors, accurate sizes, and correct placement so we teach the truth.

During Independent Writing Time, you will return to four earlier drawings: Amelia Earhart, Abraham Lincoln, the school bus, and the fish. For each one, add a setting that teaches WHERE it belongs. Pause first and pull on what you know about that topic — where would you really find it? Then add the setting carefully so the topic is standing on something, inside something, or surrounded by the place it belongs. Some setting parts will be broad and simple (like ground or water), and some may be specific objects that need shapes to be clear (like a plane for Amelia, a podium for Lincoln, a road for the bus). Keep your choices true-to-life so your picture teaches accurate information.
""",

    "hyde_summaries": [
        "How do I teach PK-1 students to add setting and environment to their informative pictures?",
        "Mini-lesson on stopping a topic from floating alone by grounding it in a real place",
        "Early-writer lesson on teaching WHERE a topic belongs — habitats, buildings, schools",
        "How do I help PK-1 writers understand that setting is information, not decoration?",
        "Scripted mini-lesson for pre-K / kindergarten on adding setting to an informative drawing",
        "Lesson on adding ground, habitat, and place clues to early-writer biographies and topic drawings",
        "Give me a PK-1 lesson on drawing the setting so the reader learns where the topic lives",
    ],
}


ML_K_CHOOSE_BEST_ADJECTIVE = {
    "grade": "K",
    "ml_number": 6,
    "day_number": None,
    "skill_title": "Choose the BEST adjective",
    "writing_trait": "Word Choice",
    "writing_mode": "all",
    "source_pdf": "Drawing, Labeling, Early Sentences mini-lessons.pdf",
    "source_page": 6,
    "lesson_triggers": ["adjectives-anchor-chart"],
    "related_ml_id": None,

    "content": """\
EARLY WRITER SKILL: Choose the BEST Adjective (Grade K, Unit 4.1)

STEP 1 (Introduce — I do; you watch & listen):
When we write, we use nouns in our sentences. A noun is a person, place, thing, or object. But writers can also make their writing MORE clear and interesting for the reader by adding adjectives to our nouns. Adjectives add details to make the noun even more clear for the reader. Today, I will teach you how to choose the best adjectives to make your sentences more clear and interesting for your readers.

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is | Writers, you know that adjectives are describing words for nouns. I like to think of adjectives like decorations for our nouns. Look at this plain cupcake. It's pretty simple and boring, but if I decorate it by adding sprinkles, it becomes more exciting. Using adjectives is like adding sprinkles to a noun.

WHY this skill is important | But there are so many adjectives to pick from that we have to learn how to choose the best for each noun. I know you have been using adjectives, but sometimes the ones we pick are not the strongest. Sometimes they are just okay. We want to learn how to pick the strongest or best adjective for a noun so that our readers imagine exactly what we are thinking.

HOW this skill works | The writer can choose the best adjective in 3 steps.

Step 1. LIST as many possible adjectives for the noun. To do this, writers think about what does the noun looks like… feels like… sounds like… smells like… tastes like. I write down all of the adjectives I can think of. (Point to large icons taped on chart paper.)

Step 2. REREAD each adjective I thought of and ask myself:
• Does this match that noun; does it fit? YES! Ask the next question. NO! Remove it from the list.
• Would this adjective fit a lot of other nouns — or is it unique and perfect for this one? YES, keep it. NO. Remove it.
• Do this for the whole list of adjectives you made in Step 1.

Step 3. CHOOSE the BEST adjective for that noun. Look at your remaining "keepers" and choose the best, the strongest one.

STEP 2B (Show the children — 5 minutes):
Let me show you how I do this. Let's pretend my teacher asked me to pick the best adjective for this noun. (Reveal/Project the horse image.) So I want to think about how I can describe this horse in a clear and interesting way. To choose the strongest adjective, I have to STEP 1: LIST all of the adjectives I can think of.

1. What does it look like? Point at picture details while Thinking Aloud about what the horse looks like. Reveal pre-written adjectives on sticky notes: tall, strong, glossy, brown.
2. What does it feel like? Point at picture details while Thinking Aloud about what the horse feels like. Reveal pre-written adjectives on sticky notes: soft, furry, silky, warm.
3. What does it sound like? Point at picture details while Thinking Aloud about what the horse sounds like. Reveal pre-written adjectives on sticky notes: loud, soft, cheerful.
4. What does it smell like? Point at picture details while Thinking Aloud about what the horse smells like. Reveal pre-written adjectives on sticky notes: grass, a barn, stinky.
5. What does it taste like? Yuck, you would never taste a horse. That would be silly. So I am not going to use adjectives to describe that.

Emphasize that we list all the adjectives we can think of that are relevant to the noun.

Now, I listed all of my adjectives. Step 2 is to REREAD each of my words and ask myself:
• Does this adjective match the noun in the picture?
• Does this adjective get used for a lot of other nouns — or is it perfect and unique?

And last, I do Step 3. I reread my "keepers" to CHOOSE the best one. During your Think Aloud, explain why it was/wasn't the best, emphasizing there is no right or wrong answer.

STEP 3 (Interact — We do; I do again, you help me):
I want to do this again, but this time I want your help. Reveal the new photo. (Reveal/Project the dog photo.) Talk them through what the image shows. Then, guide the students in brainstorming a LIST (Step 1) of potential adjectives for each sensory group using several T&Ts. Eavesdrop and note what you heard. Remind them that Step 2 requires they REREAD and keep or remove words based on fit and uniqueness. Provide a T&T for each column, giving them a chance to think through this before you identify the strongest option for that column. Guide them through Step 3 and another T&T to CHOOSE the strongest, best adjective.

STEP 4 (Close — You do; I help):
Writers, today we learned that when we add an adjective to a noun in our sentences it paints a MORE detailed picture for the reader. But we don't just want any-ol' adjective. We want the best one for THAT noun. So we learned to LIST, REREAD, and then CHOOSE the strongest adjective possible.

Today for Independent Writing Time, you will LIST adjectives for a third photo. (Reveal/Project the cat photo for all students to see and pass out the same writing template used in the mini-lesson.) After you do Step 1 and LIST, then you will REREAD (Step 2) to keep or remove before CHOOSING (Step 3) the strongest one. Now it's your turn.
""",

    "hyde_summaries": [
        "How do I teach kindergarteners to choose the best adjective for a noun?",
        "Mini-lesson on the LIST, REREAD, CHOOSE process for picking the strongest describing word",
        "K lesson on using sensory categories (looks, feels, sounds, smells, tastes) to generate adjectives",
        "How do I help K students move past generic adjectives to unique, perfect-fit ones?",
        "Scripted mini-lesson for kindergarten on choosing the BEST adjective",
        "Lesson on adjective selection for early writers — decorate your noun carefully",
        "Give me a K lesson on picking the strongest adjective for a noun from a list",
    ],
}


ML_PK1_STICKY_DOT_DETAILS = {
    "grade": "PK-1",
    "ml_number": 7,
    "day_number": None,
    "skill_title": "Develop ideas with sticky-dot details",
    "writing_trait": "Ideas",
    "writing_mode": "Inform",
    "source_pdf": "Drawing, Labeling, Early Sentences mini-lessons.pdf",
    "source_page": 7,
    "lesson_triggers": ["sticky-dots"],
    "related_ml_id": "lib-k2-s13-ml3-sticky-dot-details",

    "content": """\
PK-1 EARLY WRITER SKILL: Develop ideas with sticky-dot details

STEP 1 (Introduce — I do; you watch & listen):
Writers, we don't only write stories or share our opinions. Sometimes we write to teach information. This is called informative writing. When we write informative pieces, we are writing to tell our reader true and accurate facts about a topic. (Show icon.)

Writers, today we are going to focus on adding more details about one idea at a time so our reader can fully understand it. We will use a strategy called Sticky Dots to help us add those details and organize our writing. This will help with the trait of Ideas. (Show lightbulb.)

STEP 2A (Tell the children — 5 minutes):
WHAT the skill is | Writers, when your teacher or I say, "add more detail," we don't mean just adding more sentences at the bottom of your paper. We mean adding more information about a single idea so your reader understands it better.

WHY this skill is important | Adding more sentences about one idea helps the reader learn more facts and makes your writing clear and interesting. When each idea is fully developed, your reader doesn't have to guess or fill in missing information. This makes your writing stronger and easier to understand. It also helps you organize your thoughts so your paper is focused on one topic at a time. Using Sticky Dots teaches you how to plan your ideas carefully, elaborate on them, and improve the Trait of Ideas (light bulb).

HOW this skill works | Writers do 3 things to add more detail using Sticky Dots.

1. Elaborate: Look at your writing and find a single idea. (Reveal Fall poor example.) Each sentence in the "Fall" example is its own idea: add sticky dot color after each sentence you read. The leaves change colors. (blue dot) Animals begin to prepare for winter in the fall. (green dot) People do fun activities during fall. (yellow dot) We want to develop that idea, tell more about it. To do this, we need at least three sentences about that idea using the same sticky dot color.

2. Color: Adding a sticky dot is exciting! It helps you see where you have developed your idea, and you get to add color to your writing. This step motivates you to write more sentences about your original idea and to think of more details to make your writing stronger. (Using the revised version of "Fall," add sticky dot colors to each sentence to show how the ideas were elaborated.)

3. Check: As you add sentences, make sure each one ends with the correct punctuation. Your Sticky Dot can be a period, an exclamation point, or a question mark. This helps your writing make sense and shows your reader where each idea ends.

STEP 2B (Show the children — 5 minutes):
Writers, watch how I do this. Today our topic is Indiana. We are going to use Sticky Dots to add more details about each idea.

First, let's look at our example writing about Indiana. (Point to the anchor chart with the sentences.) The weather is getting chilly in Indiana. Plants grow fast in Indiana. The roads are very flat. We have lots of corn fields.

Writers, notice this writing is short. Each sentence is just one idea. There aren't extra details to help the reader really understand the topic.

First idea (red dot): The weather is getting chilly in Indiana. (Tape topic sentence on the board and add a red Sticky Dot at the end.) I only have one sentence, so I should add a couple more to make it clear for the reader: It starts getting cold in September. It snows for almost six months. Writers, notice how I am thinking about what a reader would want to know. A reader doesn't just want to know it's chilly — they want to know when it gets cold and what happens during the winter.

(Underline keywords in red and add the red Sticky Dot to each one.) Look how the idea grows! This is the Elaborate step; we are giving the reader more facts and details so they understand the idea fully.

Before we move on, notice our punctuation. Each sentence ends with the correct mark, using our sticky dot color.

Second idea (blue dot): Plants grow fast in Indiana. (Tape sentence on the board and add a blue Sticky Dot.) Right now I only have one sentence, but I think I need to add two or three more so the reader doesn't get confused and can understand my idea better.

The grass is always green. There are many flower and vegetable gardens all around. People mow their yards two times a week.

Writers, notice I'm asking myself: What else does the reader need to know about plants? I'm not adding a new topic; I'm adding more detail to this idea.

(Underline keywords in blue and add the blue Sticky Dot to each one.) This makes our writing exciting and interesting because the reader is learning so much more about the plants in Indiana. Finally, we Check It. Writers, notice our punctuation. Each sentence ends with the correct mark, and our Sticky Dot matches the sentence. This helps the reader know where the idea ends.

Writers, when we add more sentences, our writing becomes clearer for the reader.

STEP 3 (Interact — We do; I do again, you help me):
I want to do this again, but this time I want your help. (Reveal: The roads are very flat.) What more can we say about the roads? Turn & Talk. Reveal what you hear and write the new sentence on the anchor chart. Add an orange Sticky Dot and check punctuation.

Repeat again. (Reveal: We have lots of corn fields.) What more can we say about the corn fields? Turn & Talk. Reveal what you hear and write the new sentence on the anchor chart. Add a green Sticky Dot and check punctuation.

Writers, look at our two ideas now. Each Sticky Dot color shows a fully developed idea. You helped me elaborate to add more Sticky Dot sentences and check punctuation!

STEP 4 (Close — You do; I help):
Writers, today and every day when you write, it's important to add multiple sentences — details — about a single idea. When you do this, your reader understands your topic so much better and your writing becomes more interesting. Adding these details strengthens the Trait of Ideas by making your writing clearer.

For Independent Writing Time, you are going to add details to this Halloween writing. Your teacher has Sticky Dots for you! Let's go be writers!
""",

    "hyde_summaries": [
        "How do I teach PK-1 students to develop a single idea with multiple sentences?",
        "Mini-lesson on the Sticky Dots strategy for elaborating one idea at a time",
        "Early-writer lesson on Elaborate, Color, Check for adding details to each idea",
        "How do I help PK-1 writers go beyond one-sentence ideas to fully-developed paragraphs?",
        "Scripted mini-lesson for pre-K / kindergarten on sticky-dot details",
        "Lesson on adding at least three sentences per idea using sticky-dot color coding",
        "Give me a PK-1 lesson on elaborating ideas so the reader learns more facts",
    ],
}


ALL_DRAWING_LABELING_MLS = [
    ML_PK1_ACCURATE_SHAPES_SIZES,
    ML_PK1_REAL_PEOPLE_DETAILS,
    ML_PK1_TRUE_TO_LIFE_COLORS,
    ML_PK1_MAGNIFY_CLOSE_UP,
    ML_PK1_SETTING_ENVIRONMENT,
    ML_K_CHOOSE_BEST_ADJECTIVE,
    ML_PK1_STICKY_DOT_DETAILS,
]
