# Learner Guide

## What This System Does

This system helps you learn from PDF course material using an Intelligent Tutoring System workflow.

It can:

- estimate your level with a diagnostic QCM
- teach one knowledge component with a micro-lesson
- answer questions during the lesson
- generate adaptive practice QCMs
- explain mistakes and give hints
- track mastery and progress
- answer questions about uploaded symbol images

## How To Start

Type:

```text
start diagnostic
```

The diagnostic estimates your level across several KCs. It does not validate mastery. Mastery is validated later through practice QCMs.

## Learning Workflow

1. Type `start diagnostic`.
2. Answer the diagnostic QCM.
3. Read the micro-lesson for the selected KC.
4. Ask a question if something is unclear.
5. Type `practice`.
6. Answer the adaptive practice QCM.
7. If you make mistakes, read the feedback and type `hint` for progressive help.
8. Type `practice` again to retry.
9. When the KC is validated, type `next`.
10. Type `radar` to see your progress.

## Commands

- `start diagnostic`: start the global diagnostic QCM.
- `practice`: generate an adaptive QCM for the current KC.
- `hint`: get the next hint after mistakes.
- `next`: move to the next KC after validating the current one.
- `radar`: show progress by KC and module.
- `help`: show the in-chat guide.
- `aide`: show the in-chat guide.
- `clear image`: forget the active uploaded image.

## Answering QCMs

You can answer in the QCM widget, or type answers in chat like this:

```text
1A 2C 3B 4D
```

The system scores your answers and decides the next tutoring action.

If your score is high enough, the KC is validated.

If your score is too low, the system may:

- explain your mistakes
- detect misconceptions
- give hints
- generate a remediation micro-lesson
- ask you to retry practice

## Asking Lesson Questions

During a micro-lesson, you can ask clarification questions.

Example:

```text
Why is blue related to water?
```

For normal text questions, the system answers using the current KC and previous KCs only. This keeps the learning sequence controlled.

## Uploading Symbol Images

You can upload an image of a symbol and ask:

```text
What does this symbol mean?
```

The visual agent analyzes the image using the PDF course content.

It can explain visible elements such as:

- form
- color
- contour
- text
- pictogram

If the image contains several important elements, it explains each one and then gives a combined interpretation.

## Follow-Up Questions About The Same Image

After uploading an image, you can ask follow-up questions without uploading it again.

Examples:

```text
What about the color?
What about the form?
Why is it orange?
```

The system reuses the same image and recent visual question context.

To forget the current image, type:

```text
clear image
```

## Progress Tracking

Type:

```text
radar
```

The system shows your progress by KC and module.

The radar is based on mastery evidence from practice and checkpoints, not only from the diagnostic.

## Important Notes

- The diagnostic is only a level estimate.
- Practice QCMs are used to validate KC mastery.
- You must validate the current KC before moving to the next KC.
- Some module checkpoints may appear before continuing.
- If a question is outside the course scope, the system may refuse or redirect.
- If an uploaded image is unclear, the system may ask for a clearer image.
