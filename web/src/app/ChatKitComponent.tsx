"use client"

import { useState, useCallback, useEffect } from "react"
import { ChatKit, useChatKit, type ColorScheme } from "@openai/chatkit-react"
import GuidedTour, { TOUR_STEPS } from "./GuidedTour"

type ChatKitComponentProps = {
  userId: string
  theme: ColorScheme
  maximize: boolean
  onResponseEnd: () => void
}

type MapState = {
  lat: number
  lng: number
  zoom: number
} | null

function ChatKitComponent({
  userId,
  theme,
  maximize,
  onResponseEnd,
}: ChatKitComponentProps) {
  const [error, setError] = useState<string | null>(null)
  const [mapState, setMapState] = useState<MapState>(null)
  const [plotHtml, setPlotHtml] = useState<string | null>(null) // plot HTML
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [showTour, setShowTour] = useState(true)
  const [tourStep, setTourStep] = useState(0)

  // --- script availability effect (unchanged) ---
  useEffect(() => {
    if (typeof window === "undefined") {
      return
    }

    let timeoutId: number | undefined

    const handleLoaded = () => {
      console.log("script loaded")
      setError(null)
    }

    const handleError = () => {
      setError("Failed to load chatkit.js.")
    }

    window.addEventListener("chatkit-script-loaded", handleLoaded)
    window.addEventListener("chatkit-script-error", handleError)

    if (window.customElements?.get("openai-chatkit")) {
      handleLoaded()
    } else if (error === null) {
      timeoutId = window.setTimeout(() => {
        if (!window.customElements?.get("openai-chatkit")) {
          handleError()
        }
      }, 5000)
    }

    return () => {
      window.removeEventListener("chatkit-script-loaded", handleLoaded)
      window.removeEventListener("chatkit-script-error", handleError)
      if (timeoutId) {
        window.clearTimeout(timeoutId)
      }
    }
  }, [typeof window])

  function buildErrorResponse(message: string): Response {
    console.error(message)
    return new Response(
      JSON.stringify({
        error: message,
      }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    )
  }


  function makePlotlyResponsive(rawHtml: string): string {
  if (!rawHtml) return rawHtml

  let html = rawHtml

  // 1) Rewrite the inline style on the Plotly div
  //    from: style="height:600px; width:800px;"
  //    to:   style="height:100%; width:100%; max-width:100%; max-height:100%;"
  html = html.replace(
    /(<div[^>]*class="plotly-graph-div"[^>]*style=")([^"]*)(")/,
    (_match, start, _style, end) =>
      `${start}height:100%; width:100%; max-width:100%; max-height:100%;${end}`,
  )

  // 2) Remove explicit width/height from layout JSON (…,"width":800,"height":600,…)
  html = html.replace(/"width"\s*:\s*\d+\s*,\s*"height"\s*:\s*\d+\s*,?/, "")

  // 3) Ensure html/body fill the iframe
  const styleBlock = `
<style>
  html, body {
    margin: 0;
    padding: 0;
    height: 100%;
  }
</style>
`

  if (html.includes("</head>")) {
    html = html.replace("</head>", `${styleBlock}</head>`)
  } else {
    html = `<!DOCTYPE html><html><head>${styleBlock}</head><body>${html}</body></html>`
  }

  return html
}



  const _fetch = useCallback(
    async function customFetch(input: string | URL | Request, init?: RequestInit): Promise<Response> {
      let requestInit: RequestInit = init ?? {}
      requestInit.headers = {
        userId: userId,
      }
      try {
        const response = await fetch(input, requestInit)

        if (!response.ok) {
          const jsonResponse = await response.json()
          throw new Error(`${response.statusText}: ${JSON.stringify(jsonResponse)}`)
        }

        return response
      } catch (error) {
        console.log("error: ", error)
        const errorMessage =
          error instanceof Error ? error.message : "Unable to start fetch from the server."

        setError(errorMessage)
        return buildErrorResponse(errorMessage)
      }
    },
    [userId],
  )

  const chatkit = useChatKit({
    api: {
      // Backend base URL and ChatKit domainKey are injected at build time
      // (NEXT_PUBLIC_* are baked into the bundle). Defaults keep local dev working.
      url: `${process.env.NEXT_PUBLIC_CHATKIT_API_URL ?? "http://127.0.0.1:8000"}/chatkit`,
      domainKey: process.env.NEXT_PUBLIC_CHATKIT_DOMAIN_KEY ?? "localhost",
      fetch: _fetch,
      uploadStrategy: { type: "two_phase" },
    },
    theme: {
      colorScheme: theme,
    },
    startScreen: {
      greeting: "Bonjour. Choisissez une suggestion pour commencer, ou tapez directement votre question.",
      prompts: [
        {
          label: "Démarrer le diagnostic",
          prompt: "start diagnostic",
          icon: "star-filled",
        },
        {
          label: "Voir ma progression",
          prompt: "radar",
          icon: "chart",
        },
        {
          label: "Aide et commandes",
          prompt: "aide",
          icon: "book-open",
        },
      ],
    },
    composer: {
      placeholder: "Tapez votre message (ex : start diagnostic, radar, aide)",
      attachments: {
        enabled: true,
      },
    },
    threadItemActions: {
      feedback: true,
      retry: true,
    },

    onClientTool: async (invocation) => {
      if (invocation.name === "your_client_function_name") {
        return {}
      }
      return {}
    },
    

    // 🔹 Handle widget actions (map + plotly)
    widgets: {
      onAction: async (action, widgetItem) => {
        console.log("Widget action:", action, widgetItem)

        if (action.type === "map.show_inline") {
          const lat = Number(action.payload?.lat ?? 51.5)
          const lng = Number(action.payload?.lng ?? -0.09)
          const zoom = Number(action.payload?.zoom ?? 13)
          setMapState({ lat, lng, zoom })
          return
        }

        if (action.type === "report.open") {
          const url = String(action.payload?.url ?? "")
          if (url) {
            setPdfUrl(url)
            setPlotHtml(null)
            setMapState(null)
            return
          }
          const html = String(action.payload?.html ?? "")
          if (html) {
            const responsiveHtml = makePlotlyResponsive(html)
            setPlotHtml(responsiveHtml)
            setPdfUrl(null)
          }
          return
        }

        if (action.type === "radar.click") {
          const html = String(action.payload?.html ?? "")
          if (html) {
            setPlotHtml(makePlotlyResponsive(html))
          } else {
            console.warn("radar.click payload.html is empty")
          }
          return
        }




      },
    },

    onResponseEnd: () => {
      onResponseEnd()
    },
    onResponseStart: () => {
      setError(null)
      setShowTour(false)
    },
    onThreadLoadStart: (event) => {
      console.log("Thread load started: ", event.threadId)
    },
    onThreadLoadEnd: (event) => {
      console.log("Thread load ended: ", event.threadId)
    },
    onThreadChange: (event) => {
      console.log("Thread changed: ", event.threadId)
    },
    onError: (event) => {
      console.error("ChatKit error: ", event.error)
    },
    onLog: (event) => {
      console.log(`[${event.name}]: `, event.data)
    },
  })

  // Build the OSM URL from state
  const mapUrl =
    mapState !== null
      ? (() => {
          const { lat, lng, zoom } = mapState
          const delta = 0.02
          const bbox = [lng - delta, lat - delta, lng + delta, lat + delta].join(",")
          return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lng}`
        })()
      : null

  const hasMap = !!mapUrl
  const hasPlot = !!plotHtml
  const hasPdf = !!pdfUrl
  const showRightPane = hasMap || hasPlot || hasPdf

return (
  <div
    className={`relative h-full rounded-2xl overflow-hidden bg-white shadow-sm dark:bg-slate-900 flex flex-col ${
      maximize ? "w-full" : "w-80 ml-auto"
    }`}
  >
    {showTour && (
      <GuidedTour
        step={tourStep}
        onPrev={() => setTourStep((s) => Math.max(0, s - 1))}
        onNext={() => setTourStep((s) => Math.min(TOUR_STEPS.length - 1, s + 1))}
        onSkip={() => setShowTour(false)}
        onStart={() => {
          setShowTour(false)
          chatkit.sendUserMessage({ text: "start diagnostic" })
        }}
      />
    )}
    {!showTour && (
      <button
        type="button"
        onClick={() => {
          setTourStep(0)
          setShowTour(true)
        }}
        className="absolute left-3 top-3 z-10 rounded-full bg-slate-900/90 px-3 py-1 text-[11px] font-medium text-slate-50 shadow-sm ring-1 ring-slate-700/70 hover:bg-slate-900 dark:bg-slate-800/90 dark:text-slate-100 dark:ring-slate-600/70"
      >
        🧭 Visite guidée
      </button>
    )}
    <div className="flex flex-1 w-full min-h-0">
      <div className={showRightPane ? "w-1/2 border-r border-slate-200" : "w-full"}>
        <ChatKit control={chatkit.control} className="block h-full w-full" />
      </div>

      {showRightPane && (
        <div className="w-1/2 h-full flex flex-col bg-slate-100 dark:bg-slate-950">
          {/* Header */}
          <div className="shrink-0 flex items-center justify-between px-2 py-1 text-xs text-slate-600 dark:text-slate-300">
            <span>
              {hasPdf && "Source PDF"}
              {hasPlot && "Graphique"}
              {!hasPlot && hasMap && mapState && (
                <>
                  Carte : {mapState.lat.toFixed(4)}, {mapState.lng.toFixed(4)} (zoom {mapState.zoom})
                </>
              )}
            </span>
            <button
              type="button"
              className="
                inline-flex items-center gap-1.5
                rounded-full
                bg-slate-900/90 dark:bg-slate-800/90
                px-3 py-1
                text-[11px] font-medium
                text-slate-50 dark:text-slate-100
                shadow-sm
                ring-1 ring-slate-700/70 dark:ring-slate-600/70
                hover:bg-slate-900 hover:dark:bg-slate-700
                hover:ring-slate-500/80
                transition-colors transition-shadow
              "
              onClick={() => {
                setMapState(null)
                setPlotHtml(null)
                setPdfUrl(null)
              }}
            >
              <span className="text-[13px] leading-none">×</span>
              <span>Fermer</span>
            </button>
          </div>

          {/* Content: fills remaining height */}
          <div className="flex-1 min-h-0">
            {hasPdf ? (
              <iframe
                title="PDF source"
                src={pdfUrl ?? ""}
                className="h-full w-full border-0 bg-white"
              />
            ) : hasPlot ? (
              <iframe
                title="Plotly chart"
                srcDoc={plotHtml ?? ""}
                className="h-full w-full border-0 bg-white"
                sandbox="allow-scripts allow-same-origin"
              />
            ) : hasMap ? (
              <iframe
                title="Inline OSM map"
                src={mapUrl as string}
                className="h-full w-full border-0"
                loading="lazy"
              />
            ) : null}
          </div>
        </div>
      )}
    </div>

    {error && (
      <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/95 p-6 text-center backdrop-blur-sm dark:bg-slate-900/95">
        <div className="max-w-xs space-y-3">
          <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
            Le chat n&apos;a pas pu se charger.
          </p>
          <p className="break-words text-xs text-slate-500 dark:text-slate-400">
            {error}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex items-center rounded-full bg-slate-900 px-4 py-1.5 text-xs font-medium text-white hover:opacity-90 dark:bg-slate-100 dark:text-slate-900"
          >
            Réessayer
          </button>
        </div>
      </div>
    )}
  </div>
)

}

export default ChatKitComponent
