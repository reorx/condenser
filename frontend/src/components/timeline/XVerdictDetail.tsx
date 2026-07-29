// The "why" behind a For You verdict, in the item detail pane (plan Phase 4).
//
// The badge on the card is a claim; this is the evidence for it — which labeled
// tweets voted, how close each one was, and the score they produced. That trail
// is the whole reason Phase 4 badges instead of hiding: a verdict you can audit
// is one you can learn to trust (or catch being wrong and correct with a thumb).
import { xTweetUrl } from '@/lib/sources';
import type { XVerdict, XVerdictChannel, XVerdictMeta, XVerdictNeighbor } from '@/lib/types';

const VERDICT_LABEL: Record<XVerdict, string> = {
  positive: '推荐',
  neutral: '中性',
  negative: '可能不感兴趣',
};

// The channels in the reader's terms. Keyed by the backend's channel letters; an
// unknown key (a future channel) degrades to the letter rather than hiding the row.
const CHANNEL_LABEL: Record<string, string> = {
  a: '作者记录',
  b: '话题相似',
  c: '内容属性',
  d: '词面特征',
};

const VOTE_LABEL: Record<XVerdict, string> = {
  positive: '判正',
  neutral: '中性',
  negative: '判负',
};

// The two ways the judge declines to commit, in the reader's terms.
const REASON_LABEL: Record<string, string> = {
  out_of_domain: '与你标注过的内容都不相似，不作判断',
  no_text: '没有可判断的文本',
};

const LABEL_MARK: Record<XVerdictNeighbor['label'], string> = {
  up: '👍',
  down: '👎',
  save: '🔖',
};

function NeighborRow({ neighbor }: { neighbor: XVerdictNeighbor }) {
  return (
    <li className="flex items-center gap-2">
      <span aria-hidden>{LABEL_MARK[neighbor.label]}</span>
      <a
        href={xTweetUrl(neighbor.tweet_id, neighbor.handle)}
        target="_blank"
        rel="noreferrer"
        className="truncate hover:underline"
        title={`${neighbor.tweet_id} · 距离 ${neighbor.distance}`}
      >
        {neighbor.handle ? `@${neighbor.handle}` : neighbor.tweet_id}
      </a>
      <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">{neighbor.distance.toFixed(2)}</span>
    </li>
  );
}

function evidenceLine(channel: XVerdictChannel): string | null {
  // Channel D names words, channel C names attributes, channel A names the account
  // and your record with it; channel B's neighbours are rendered above from the
  // meta's top level, so its row is just the vote.
  if (channel.handle) {
    return `@${channel.handle} · 你踩过 ${channel.down ?? 0} 次，赞过 ${channel.up ?? 0} 次`;
  }
  const pairs = channel.tokens ?? channel.flags ?? [];
  if (pairs.length === 0) return null;
  return pairs.map(([name, weight]) => `${name} ${weight > 0 ? '+' : ''}${weight.toFixed(2)}`).join(' · ');
}

function ChannelRow({ channelKey, channel }: { channelKey: string; channel: XVerdictChannel }) {
  const evidence = evidenceLine(channel);
  return (
    <li>
      <div className="flex items-center gap-2">
        <span>{CHANNEL_LABEL[channelKey] ?? channelKey}</span>
        {channel.verdict && (
          <span className={channel.verdict === 'negative' ? 'text-destructive' : 'text-muted-foreground'}>
            {VOTE_LABEL[channel.verdict]}
          </span>
        )}
        {channel.shadow && <span className="text-muted-foreground">影子（不参与投票）</span>}
        <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">{channel.score.toFixed(2)}</span>
      </div>
      {evidence && <div className="truncate text-xs text-muted-foreground">{evidence}</div>}
    </li>
  );
}

interface Props {
  verdict: XVerdict;
  meta: XVerdictMeta | null;
}

export function XVerdictDetail({ verdict, meta }: Props) {
  const neighbors = meta?.neighbors ?? [];
  const reason = meta?.reason ? REASON_LABEL[meta.reason] : null;
  const channels = Object.entries(meta?.channels ?? {});

  return (
    <div className="space-y-1">
      <div>
        {VERDICT_LABEL[verdict]}
        {typeof meta?.score === 'number' && (
          <span className="ml-1.5 text-muted-foreground tabular-nums">score {meta.score.toFixed(2)}</span>
        )}
      </div>
      {reason && <div className="text-muted-foreground">{reason}</div>}
      {neighbors.length > 0 && (
        <>
          <div className="text-muted-foreground">依据（你标注过的最近邻）：</div>
          <ul className="space-y-0.5">
            {neighbors.map((neighbor) => (
              <NeighborRow key={neighbor.tweet_id} neighbor={neighbor} />
            ))}
          </ul>
        </>
      )}
      {channels.length > 0 && (
        <>
          <div className="text-muted-foreground">各通道投票：</div>
          <ul className="space-y-0.5">
            {channels.map(([key, channel]) => (
              <ChannelRow key={key} channelKey={key} channel={channel} />
            ))}
          </ul>
        </>
      )}
      {meta?.model && (
        <div className="text-xs text-muted-foreground">
          {meta.model}
          {meta.algo ? ` / ${meta.algo}` : ''}
        </div>
      )}
    </div>
  );
}
