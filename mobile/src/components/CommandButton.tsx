import React from 'react';
import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import type { Capability } from '../types';
import { theme } from '../theme';

interface CommandButtonProps {
  capability: Capability;
  onPress: (capability: Capability) => void;
  disabled?: boolean;
}

const riskColors: Record<string, { bg: string; border: string }> = {
  low: { bg: theme.bg.green, border: theme.green.DEFAULT },
  medium: { bg: theme.bg.amber, border: theme.amber.DEFAULT },
  high: { bg: theme.bg.red, border: theme.red.DEFAULT },
};

export const CommandButton: React.FC<CommandButtonProps> = ({ capability, onPress, disabled }) => {
  const colors = riskColors[capability.risk_level] || riskColors.low;
  return (
    <TouchableOpacity
      style={[styles.button, { backgroundColor: colors.bg, borderColor: colors.border } as any]}
      onPress={() => onPress(capability)}
      disabled={disabled || !capability.supported}
      activeOpacity={0.7}
    >
      <Text style={styles.text}>{capability.name}</Text>
      {capability.requires_confirmation && <Text style={styles.hint}></Text>}
      {!capability.supported && <Text style={styles.unsupported}> (not supported)</Text>}
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  button: {
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginVertical: 4,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  text: {
    color: theme.text.primary,
    fontSize: 14,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  hint: {
    fontSize: 12,
  },
  unsupported: {
    color: theme.text.secondary,
    fontSize: 12,
  },
});
