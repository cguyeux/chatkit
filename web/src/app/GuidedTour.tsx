"use client"

type TourStep = {
  emoji: string
  title: string
  body: string
}

const TOUR_STEPS: TourStep[] = [
  {
    emoji: "🧭",
    title: "Formateur intelligent : cartographie opérationnelle",
    body: "Cet assistant vous fait réviser le mémento officiel gestion opérationnelle et commandement (formes, couleurs, symboles), à votre rythme.",
  },
  {
    emoji: "🎯",
    title: "1. Un diagnostic pour commencer",
    body: "Quelques questions rapides estiment votre niveau sur chaque thème. Pas de note ici, juste un point de départ pour la suite.",
  },
  {
    emoji: "📚",
    title: "2. Une mini-leçon, puis un quiz",
    body: "Pour chaque notion à travailler : une leçon courte, puis un quiz adapté à votre niveau. Vous pouvez poser vos questions à tout moment.",
  },
  {
    emoji: "💡",
    title: "3. Des indices en cas d'erreur",
    body: "Une mauvaise réponse ? Demandez un indice : il vous guide vers la solution sans vous la donner directement.",
  },
  {
    emoji: "📷",
    title: "4. Une photo suffit",
    body: "Symbole vu sur le terrain ou dans le mémento : joignez une photo à votre message, l'assistant l'identifie et vous l'explique.",
  },
  {
    emoji: "📊",
    title: "5. Votre progression en un coup d'œil",
    body: "Tapez « radar » à tout moment pour voir un graphique de votre progression par thème. Bloqué ? Tapez « aide », ou cliquez sur le (?) en haut à droite pour revoir cette visite ou ouvrir la documentation complète.",
  },
]

type GuidedTourProps = {
  step: number
  onNext: () => void
  onPrev: () => void
  onSkip: () => void
  onStart: () => void
}

function GuidedTour({ step, onNext, onPrev, onSkip, onStart }: GuidedTourProps) {
  const current = TOUR_STEPS[step]
  const isLast = step === TOUR_STEPS.length - 1
  const isFirst = step === 0

  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/95 p-4 backdrop-blur-sm dark:bg-slate-900/95">
      <div className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-lg dark:border-slate-700 dark:bg-slate-800">
        <div className="flex items-start justify-between gap-3">
          <span className="text-3xl leading-none" aria-hidden="true">
            {current.emoji}
          </span>
          <button
            type="button"
            onClick={onSkip}
            className="shrink-0 text-xs font-medium text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          >
            Passer
          </button>
        </div>

        <div>
          <h1 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {current.title}
          </h1>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
            {current.body}
          </p>
        </div>

        <div className="flex items-center justify-center gap-1.5">
          {TOUR_STEPS.map((_, i) => (
            <span
              key={i}
              className={`h-1.5 w-1.5 rounded-full ${
                i === step ? "bg-slate-900 dark:bg-slate-100" : "bg-slate-300 dark:bg-slate-600"
              }`}
            />
          ))}
        </div>

        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={onPrev}
            disabled={isFirst}
            className="rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 disabled:opacity-0 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Précédent
          </button>
          {isLast ? (
            <button
              type="button"
              onClick={onStart}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
            >
              Démarrer le diagnostic
            </button>
          ) : (
            <button
              type="button"
              onClick={onNext}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
            >
              Suivant
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export { TOUR_STEPS }
export default GuidedTour
