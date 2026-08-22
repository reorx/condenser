import { HnGlyph } from '@/components/HnGlyph';
import { HackerNewsSection } from '@/components/subscriptions/HackerNewsSection';
import { RssSection } from '@/components/subscriptions/RssSection';
import { TelegramSection } from '@/components/subscriptions/TelegramSection';
import { XSection } from '@/components/subscriptions/XSection';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { RssGlyph } from '@/components/RssGlyph';
import { TgGlyph } from '@/components/TgGlyph';
import { XGlyph } from '@/components/XGlyph';

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
            <TabsTrigger value="x" className="px-3">
              <XGlyph className="size-4 rounded-[4px]" />X
            </TabsTrigger>
            <TabsTrigger value="rss" className="px-3">
              <RssGlyph className="size-4 rounded-[4px]" />
              RSS
            </TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="telegram">
          <TelegramSection />
        </TabsContent>
        <TabsContent value="hn">
          <HackerNewsSection />
        </TabsContent>
        <TabsContent value="x">
          <XSection />
        </TabsContent>
        <TabsContent value="rss">
          <RssSection />
        </TabsContent>
      </Tabs>
    </>
  );
}
