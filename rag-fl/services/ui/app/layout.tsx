import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG-FL Observability",
  description: "Pick a file and explore what exactly is held there.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-900 text-slate-100">{children}</body>
    </html>
  );
}
