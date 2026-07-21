import { HnGlyph } from '@/components/HnGlyph';
import { HackerNewsSection } from '@/components/subscriptions/HackerNewsSection';
import { TelegramSection } from '@/components/subscriptions/TelegramSection';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TgGlyph } from '@/components/TgGlyph';

export function SubscriptionsView() {
  return (
    <>
      <div className="border-b px-4 py-3 sm:px-5">
        <h1 className="text-base font-semibold tracking-tight">Subscriptions</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Manage what each source collects. Exclude keywords live in <span className="font-medium">Filters</span>.
        </p>
      </div>

      <Tabs defaultValue="telegram" className="gap-0">
        <div className="border-b px-4 py-2 sm:px-5">
          <TabsList>
            <TabsTrigger value="telegram" className="px-3">
              <TgGlyph className="size-4" />
              Telegram
            </TabsTrigger>
            <TabsTrigger value="hn" className="px-3">
              <HnGlyph className="size-4 rounded-[4px] text-[10px]" />
              Hacker News
            </TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="telegram">
          <TelegramSection />
        </TabsContent>
        <TabsContent value="hn">
          <HackerNewsSection />
        </TabsContent>
      </Tabs>
    </>
  );
}
