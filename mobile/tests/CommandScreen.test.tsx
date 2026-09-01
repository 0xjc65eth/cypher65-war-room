import { act, render, screen } from '@testing-library/react-native';
import * as snapshotHook from '../src/hooks/useSnapshot';
import { CommandScreen } from '../src/screens/Command/CommandScreen';

jest.mock('../src/hooks/useSnapshot');
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: jest.fn() }),
}));
jest.mock('../src/api/client', () => ({
  fetchShareDist: jest.fn().mockResolvedValue({
    labels: [],
    count: 0,
    target_diff: null,
    target_bucket: null,
    datasets: [],
  }),
}));

describe('CommandScreen', () => {
  it('renders the command center heading', async () => {
    jest.spyOn(snapshotHook, 'useSnapshot').mockReturnValue({
      snapshot: { ts: Date.now() / 1000, worker: {}, pool: {}, network: {} },
      refreshing: false,
      error: null,
      refresh: jest.fn(),
    });

    render(<CommandScreen />);
    // Flush the already-resolved share request explicitly. Polling for its UI
    // made this test depend on runner scheduling during cold suite startup.
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText('Command Center')).toBeTruthy();
    expect(screen.getByText(/No shares yet/)).toBeTruthy();
  });

  it('renders the Live→Probability share difficulty section', async () => {
    jest.spyOn(snapshotHook, 'useSnapshot').mockReturnValue({
      snapshot: { ts: Date.now() / 1000, worker: {}, pool: {}, network: {} },
      refreshing: false,
      error: null,
      refresh: jest.fn(),
    });

    render(<CommandScreen />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText('Share Difficulty')).toBeTruthy();
    expect(screen.getByText(/P\(block\) → Block Model/)).toBeTruthy();
    // The mocked client returns an empty session — chart falls back gracefully.
    expect(screen.getByText(/No shares yet/)).toBeTruthy();
  });
});
