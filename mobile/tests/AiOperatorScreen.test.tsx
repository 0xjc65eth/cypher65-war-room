import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { AiOperatorScreen } from '../src/screens/AI/AiOperatorScreen';
import { queryAiOperator } from '../src/api/client';

jest.mock('../src/api/client', () => {
  const actual = jest.requireActual('../src/api/client');
  return {
    ...actual,
    queryAiOperator: jest.fn(),
  };
});

const mockedQuery = queryAiOperator as jest.MockedFunction<typeof queryAiOperator>;

describe('AiOperatorScreen', () => {
  beforeEach(() => {
    mockedQuery.mockReset();
  });

  it('shows only the validated backend answer', async () => {
    mockedQuery.mockResolvedValue('Observed fleet status is healthy.');
    render(<AiOperatorScreen />);

    fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), 'Fleet status?');
    fireEvent.press(screen.getByLabelText('Send question'));

    expect(await screen.findByText('Observed fleet status is healthy.')).toBeTruthy();
    expect(mockedQuery).toHaveBeenCalledWith('Fleet status?');
    expect(screen.queryByTestId('ai-operator-error')).toBeNull();
  });

  it('shows an explicit unavailable state and no fabricated answer', async () => {
    mockedQuery.mockRejectedValue(new Error('network failed'));
    render(<AiOperatorScreen />);

    fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), 'Fleet status?');
    fireEvent.press(screen.getByLabelText('Send question'));

    expect(await screen.findByTestId('ai-operator-error')).toBeTruthy();
    expect(screen.getByText('AI Operator is unavailable. No response was generated.')).toBeTruthy();
    expect(screen.queryByText(/SIMULATED/)).toBeNull();
  });

  it.each([
    [402, 'AI Operator requires an active Premium license.'],
    [429, 'AI Operator rate limit reached. Try again later.'],
  ])('explains HTTP %s without converting it into an answer', async (status, message) => {
    mockedQuery.mockRejectedValue({ isAxiosError: true, response: { status } });
    render(<AiOperatorScreen />);

    fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), 'Fleet status?');
    fireEvent.press(screen.getByLabelText('Send question'));

    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.queryByText(/SIMULATED/)).toBeNull();
  });

  it('prevents a duplicate request while one is pending', async () => {
    let resolveQuery: (value: string) => void = () => {};
    mockedQuery.mockImplementation(() => new Promise((resolve) => {
      resolveQuery = resolve;
    }));
    render(<AiOperatorScreen />);

    fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), 'Fleet status?');
    fireEvent.press(screen.getByLabelText('Send question'));
    fireEvent.press(screen.getByLabelText('Send question'));

    expect(mockedQuery).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Send question').props.accessibilityState).toEqual({
      disabled: true,
      busy: true,
    });
    resolveQuery('Real response');
    await waitFor(() => expect(screen.getByText('Real response')).toBeTruthy());
  });
});
