import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppShell } from "@/components/shell/app-shell";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { MissionControlProvider } from "@/state/mission-control";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Cloudeo Mission Control",
    template: "%s · Cloudeo",
  },
  description: "Mission control for autonomous work: WorkOrders, evidence and verification.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}>
      <body>
        <MissionControlProvider>
          <TooltipProvider delayDuration={300}>
            <AppShell>{children}</AppShell>
            <Toaster theme="dark" position="bottom-center" />
          </TooltipProvider>
        </MissionControlProvider>
      </body>
    </html>
  );
}
