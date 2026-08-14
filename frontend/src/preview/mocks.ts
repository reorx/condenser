// Mock data for the component preview page (`/preview.html`, dev-only). Lets us render
// real components with deterministic data and screenshot them to verify visual changes.
import type { DisplayMessage, HnStory, LinkPreview, TimelineItem, XTweet } from '@/lib/types';

export const CHANNEL_ID = 1833253016;

export const channelLabels = new Map<number, string>([[CHANNEL_ID, 'yihong0618 和朋友们的频道']]);

/** Build a DisplayMessage with sane defaults; override only what a case cares about. */
export function makeMsg(over: Partial<DisplayMessage> & Pick<DisplayMessage, 'id'>): DisplayMessage {
  return {
    channel_id: CHANNEL_ID,
    date: '2026-06-23T03:12:00+00:00',
    is_edited: false,
    edit_date: null,
    sender_id: null,
    sender_name: null,
    text: null,
    is_album: false,
    grouped_id: null,
    media_items: [],
    webpage: null,
    is_forwarded: false,
    forward_info: null,
    views: null,
    forwards_count: null,
    replies_count: null,
    raw_message_ids: [over.id],
    ...over,
  };
}

/** Wrap a DisplayMessage in its multi-source item envelope (flags live here). */
export function makeItem(
  over: Partial<DisplayMessage> & Pick<DisplayMessage, 'id'>,
  flags: { is_read?: boolean; is_saved?: boolean } = {},
): TimelineItem {
  const msg = makeMsg(over);
  return {
    source: 'telegram',
    key: `tg:${msg.channel_id}:${msg.id}`,
    datetime: msg.date,
    is_read: flags.is_read ?? false,
    is_saved: flags.is_saved ?? false,
    telegram: msg,
  };
}

/** Wrap an HnStory in its item envelope; override only what a case cares about. */
export function makeHnItem(
  over: Partial<HnStory> & Pick<HnStory, 'id'>,
  flags: { is_read?: boolean; is_saved?: boolean } = {},
): TimelineItem {
  const hn: HnStory = {
    title: 'An HN story',
    url: 'https://example.com/post',
    domain: 'example.com',
    author: 'alice',
    type: 'story',
    text: null,
    submitted_at: '2026-06-23T01:00:00Z',
    first_seen_at: '2026-06-23T03:09:00Z',
    qualified_at: '2026-06-23T03:09:00Z',
    score: 100,
    comments_count: 10,
    day_rank: null,
    peak_rank: null,
    backfilled: false,
    preview: null,
    ...over,
  };
  return {
    source: 'hn',
    key: `hn:${hn.id}`,
    // the admission stamp is the timeline position (v14); a story with none was
    // never admitted, and only search can reach it
    datetime: hn.qualified_at ?? hn.first_seen_at,
    is_read: flags.is_read ?? false,
    is_saved: flags.is_saved ?? false,
    hn,
  };
}

/** Wrap a tweet in its item envelope. The sort timestamp is feed-dependent, exactly
 *  as the backend computes it: For You = first sighting, a followed account = post time. */
export function makeXItem(
  over: Partial<XTweet> & Pick<XTweet, 'id'>,
  flags: { is_read?: boolean; is_saved?: boolean } = {},
): TimelineItem {
  const x: XTweet = {
    author_id: '18824096',
    author_handle: 'recatm',
    author_name: '西乔 XiQiao',
    text: 'a tweet',
    created_at: '2026-06-23T02:38:39Z',
    first_seen_at: '2026-06-23T03:08:00Z',
    media: null,
    metrics: { reply_count: 34, retweet_count: 2, like_count: 128 },
    quote: null,
    rt_of_handle: null,
    reply_to_id: null,
    article: null,
    urls: null,
    feed: 'foryou',
    feed_kind: 'home',
    verdict: null,
    verdict_meta: null,
    ...over,
  };
  return {
    source: 'x',
    key: `x:${x.id}`,
    datetime: x.feed_kind === 'home' ? x.first_seen_at : (x.created_at ?? x.first_seen_at),
    is_read: flags.is_read ?? false,
    is_saved: flags.is_saved ?? false,
    x,
  };
}

/** Sample previews for the LinkPreviewCard gallery (images 404 in the harness; layout still shows). */
export const samplePreviews: LinkPreview[] = [
  {
    url: 'https://example.com/a-very-cool-article-about-things-that-matter',
    title: 'A very cool article about things that matter in 2026',
    description:
      'The meta description goes here and is clamped to three lines so very long summaries do not blow out the card height in the preview pane.',
    image: 'https://example.com/cover.png',
    site_name: 'Example News',
    source: 'fetched',
    tg_image_message_id: null,
    error: null,
  },
  {
    url: 'https://github.com/encode/httpx',
    title: 'encode/httpx: A next-generation HTTP client for Python',
    description: null,
    image: null,
    site_name: 'GitHub',
    source: 'fetched',
    tg_image_message_id: null,
    error: null,
  },
  {
    url: 'https://broken.example.com/gone',
    title: null,
    description: null,
    image: null,
    site_name: null,
    source: 'fetched',
    tg_image_message_id: null,
    error: 'request timed out',
  },
];

export const dayItems: TimelineItem[] = [
  makeItem({
    id: 13554,
    date: '2026-06-23T03:13:00+00:00',
    text: 'Two links, no Telegram preview — click the card to open the pane: https://example.com/post and https://github.com/encode/httpx',
  }),
  makeItem({
    id: 13553,
    text: '10 年的诗写满了这个朋友心境的变化，真是个有趣的人啊。',
    is_forwarded: true,
    forward_info: {
      from_channel_id: 999,
      from_channel_name: '诗词集',
      from_user_id: null,
      from_user_name: null,
      from_message_id: 1,
      original_date: null,
      post_author: null,
    },
  }),
  makeItem({
    id: 13552,
    date: '2026-06-23T03:11:30+00:00',
    text: '风语轩窗寒夜长，木渐黄，露成霜。云颓月沉，乌啼催泪行。为问心事尚几许？长空外，惟苍茫。',
    is_edited: true,
  }),
  makeItem(
    {
      id: 13551,
      date: '2026-06-23T03:11:00+00:00',
      text: '这是一条已读消息，未读 dot 应当透明不可见，频道头像左侧不应出现圆点。',
    },
    { is_read: true },
  ),
  makeItem(
    {
      id: 13550,
      date: '2026-06-23T03:10:00+00:00',
      text: '这是一条已保存的未读消息，书签为琥珀色，dot 浮在头像左侧。',
    },
    { is_saved: true },
  ),
  // Hacker News cards: external story w/ day rank, long self-post (clamp toggle), job post.
  makeHnItem({
    id: 44001234,
    title: 'Show HN: A self-hosted Telegram + HN aggregating reader',
    url: 'https://example.com/condenser',
    score: 128,
    comments_count: 42,
    day_rank: 3,
    peak_rank: 5,
  }),
  makeHnItem(
    {
      id: 44001235,
      title: 'Ask HN: How do you archive the front page?',
      url: null,
      domain: null,
      text:
        '<p>Every day the front page turns over and the good stuff is gone. ' +
        'What do people use to keep a personal archive?</p><p>I have tried RSS, ' +
        'bookmarking, and a cron job that scrapes the API, but nothing sticks. ' +
        'Ideally I want per-day top-N with read state, like a Google Reader for HN. ' +
        'Links like <a href="https://example.com/tool">this tool</a> get close. ' +
        '<pre><code>curl https://hacker-news.firebaseio.com/v0/topstories.json</code></pre> ' +
        'is where I started.</p>',
      score: 87,
      comments_count: 63,
      day_rank: 7,
    },
    { is_saved: true },
  ),
  makeHnItem(
    {
      id: 44001236,
      title: 'Acme Corp (YC S26) is hiring founding engineers',
      url: 'https://example.com/jobs',
      type: 'job',
      score: 1,
      comments_count: 0,
      day_rank: 28,
    },
    { is_read: true },
  ),
  // X cards: plain tweet w/ link, quote tweet, retweet, article, followed-account feed.
  makeXItem({
    id: '2080557548659441713',
    text: '这两天在主线工作上的进展给我带来了非常大的成就感 —— 一个只属于自己的阅读器，终于把 X 也接进来了。 https://example.com/condenser',
  }),
  makeXItem(
    {
      id: '2080301572739695041',
      text: '完蛋了，这个说法太准确了 https://t.co/fRiMeyu599',
      quote: {
        id: '2080267011654144075',
        author_handle: 'MaxForAI',
        author_name: 'Max For AI',
        text: '所有的推荐算法最终都会变成同一个东西：一个你无法关掉的、永远在采样的老虎机。',
        created_at: '2026-06-23T00:21:19Z',
        media: null,
        metrics: { reply_count: 240, retweet_count: 18, like_count: 770 },
        urls: null,
      },
    },
    { is_saved: true },
  ),
  makeXItem({
    id: '2080433142456864773',
    author_handle: 'geoffreylitt',
    author_name: 'Geoffrey Litt',
    rt_of_handle: 'colebemis',
    text: 'RT @colebemis: The best interface for an LLM is the one you already know how to use.',
    metrics: { reply_count: 0, retweet_count: 32, like_count: 0 },
  }),
  makeXItem(
    {
      id: '2080441004881215520',
      author_handle: 'lawrencecchen',
      author_name: 'Lawrence Chen',
      text: 'Superrepos and why Claude Code is the best worktree manager',
      article: {
        title: 'Superrepos and why Claude Code is the best worktree manager',
        previewText:
          'Different workloads are best parallelized in different ways. Common ways include: Worktrees, multiple checkouts (git clone multiple times), microVMs/remote sandboxes via E2B/Freestyle/Daytona/Modal…',
      },
    },
    { is_read: true },
  ),
  makeXItem({
    id: '2080215574957928545',
    author_handle: 'novoreorx',
    author_name: 'Reorx',
    feed: 'novoreorx',
    feed_kind: 'user',
    text: '关注的人的时间线按发布时间排序，和 TG 频道一个语义；For You 才按抓取时间。',
    metrics: { reply_count: 3, retweet_count: 1, like_count: 26 },
  }),
];
