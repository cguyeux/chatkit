import type { Metadata } from "next"
import "./globals.css"
import Script from "next/script"

export const metadata: Metadata = {
    title: "Formateur cartographie opérationnelle",
    description: "Assistant de formation sur le mémento gestion opérationnelle et commandement",
}


export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode
}>) {
    return (
        <html lang="fr">
            <head>
                <Script
                    src="https://cdn.platform.openai.com/deployments/chatkit/chatkit.js"
                    strategy="beforeInteractive"
                />
            </head>
            <body className="antialiased">{children}</body>
        </html>
    )
}
