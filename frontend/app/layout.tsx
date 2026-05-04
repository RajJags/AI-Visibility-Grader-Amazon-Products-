import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "AI Visibility Grader",
  description:
    "Find out how often AI shopping assistants recommend your Amazon product — before your competitors do.",
  openGraph: {
    title: "AI Visibility Grader",
    description: "Grade your brand's AI search visibility. Free. No signup.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.className}>
      <body className="min-h-screen bg-white text-neutral-950">{children}</body>
    </html>
  );
}

