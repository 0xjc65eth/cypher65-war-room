import React from 'react';
import { render, screen } from '@testing-library/react-native';
import { CommandScreen } from '../src/screens/Command/CommandScreen';
import * as snapshotHook from '../src/hooks/useSnapshot';

jest.mock('../src/hooks/useSnapshot');

describe('CommandScreen', () => {
  it('renders the command center heading', () => {
    jest.spyOn(snapshotHook, 'useSnapshot').mockReturnValue({
      snapshot: { ts: Date.now() / 1000, worker: {}, pool: {}, network: {} },
      refreshing: false,
      error: null,
      refresh: jest.fn(),
    });

    render(<CommandScreen />);
    expect(screen.getByText('Command Center')).toBeTruthy();
  });
});
