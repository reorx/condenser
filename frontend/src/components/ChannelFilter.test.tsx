import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Inbox } from 'lucide-react';

import { AllChannelsHidden, ChannelFilter } from './ChannelFilter';
import type { ChannelSummary } from '@/hooks/useChannelFilter';

const channels: ChannelSummary[] = [
  { id: 1, name: 'Alpha', count: 3 },
  { id: 2, name: 'Bravo', count: 2 },
];

function setup(props: Partial<React.ComponentProps<typeof ChannelFilter>> = {}) {
  const onToggle = vi.fn();
  const onClear = vi.fn();
  render(
    <ChannelFilter
      channels={channels}
      hidden={props.hidden ?? new Set<number>()}
      onToggle={props.onToggle ?? onToggle}
      onClear={props.onClear ?? onClear}
      {...props}
    />,
  );
  return { onToggle: props.onToggle ?? onToggle, onClear: props.onClear ?? onClear, user: userEvent.setup() };
}

describe('ChannelFilter', () => {
  it('renders a filter trigger button', () => {
    setup();
    expect(screen.getByRole('button', { name: /filter channels/i })).toBeInTheDocument();
  });

  it('opens a dropdown listing each channel with its message count', async () => {
    const { user } = setup();

    await user.click(screen.getByRole('button', { name: /filter channels/i }));

    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Bravo')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('calls onToggle with the channel id when a channel row is clicked', async () => {
    const { user, onToggle } = setup();

    await user.click(screen.getByRole('button', { name: /filter channels/i }));
    await user.click(await screen.findByRole('button', { name: /Alpha/ }));

    expect(onToggle).toHaveBeenCalledWith(1);
  });

  it('dims the avatar (opacity) of a hidden channel as the off-state indicator', async () => {
    const { user } = setup({ hidden: new Set([2]) });

    await user.click(screen.getByRole('button', { name: /filter channels/i }));

    const hiddenRow = await screen.findByRole('button', { name: /Bravo/ });
    const visibleRow = screen.getByRole('button', { name: /Alpha/ });
    expect(hiddenRow.querySelector('img')).toHaveClass('opacity-30');
    expect(visibleRow.querySelector('img')).not.toHaveClass('opacity-30');
  });

  it('reflects the hidden count on the trigger when channels are filtered', () => {
    setup({ hidden: new Set([2]) });
    expect(screen.getByRole('button', { name: /1 hidden/i })).toBeInTheDocument();
  });

  it('offers a "Show all" action only while something is hidden, and it calls onClear', async () => {
    const { user, onClear } = setup({ hidden: new Set([2]) });

    await user.click(screen.getByRole('button', { name: /filter channels/i }));
    const showAll = await screen.findByRole('button', { name: /show all/i });
    await user.click(showAll);

    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('hides the "Show all" action when nothing is hidden', async () => {
    const { user } = setup();

    await user.click(screen.getByRole('button', { name: /filter channels/i }));
    await screen.findByText('Alpha');

    expect(screen.queryByRole('button', { name: /show all/i })).not.toBeInTheDocument();
  });
});

describe('AllChannelsHidden', () => {
  it('renders the empty state and recovers via "Show all"', async () => {
    const onClear = vi.fn();
    render(<AllChannelsHidden icon={Inbox} onClear={onClear} />);

    expect(screen.getByText(/all channels are hidden/i)).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: /show all/i }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
